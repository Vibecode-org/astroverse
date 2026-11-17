"""Explicit synthetic temporal acceptance; fixtures/logs remain outside the repo.

Run inside existing test image. Process-cold never means cold OS page cache.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.metadata
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode, quote

from tests.benchmark_api_load import fetch, payload, percentile, rss

BUDGETS = dict(selection_p95_ms=100, selection_p99_ms=250,
               positions_p95_ms=250, positions_p99_ms=500,
               accepted_p95_ms=500, accepted_p99_ms=1500,
               backend_peak_mib=512, late_growth_mib=32,
               sectors=16, members=2048, sector_members=128,
               response_bytes=256*1024)


def distribution(values):
    return dict(samples=len(values), p50=percentile(values, .50),
                p95=percentile(values, .95), p99=percentile(values, .99),
                maximum=max(values)) if values else dict(samples=0)


@contextmanager
def server(path):
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'ASTROVERSE_TEMPORAL_DB': str(path)}
    with tempfile.TemporaryFile() as logs:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'tests.temporal_provider:app',
                                    '--host', '127.0.0.1', '--port', str(port), '--no-access-log'],
                                   env=env, stdout=logs, stderr=logs)
        samples, stopped = [], threading.Event()
        def sample():
            while not stopped.wait(.05):
                value = rss(process.pid)
                if value:
                    samples.append((time.monotonic(), value['VmRSS'], value.get('VmHWM', 0)))
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        started = time.monotonic()
        try:
            while time.monotonic()-started < 60:
                if process.poll() is not None:
                    logs.seek(0)
                    raise RuntimeError(logs.read().decode()[-6000:])
                try:
                    health = payload(fetch(base, '/api/health'))
                    break
                except OSError:
                    time.sleep(.05)
            else:
                raise RuntimeError('temporal provider readiness deadline')
            yield base, process.pid, samples, time.monotonic()-started, health
        finally:
            stopped.set()
            sampler.join()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def query(at, x, radius):
    return '/api/positions/v1/nearby?' + urlencode(dict(at=at, anchor='synthetic-0000000',
        dx=0, dy=0, dz=0, ox=x, oy=0, oz=0, radius=radius))


def exercise(base, requests, seconds):
    """Bounded client models the manager's discovery + four sector workers.

    Browser acceptance separately measures actual manager and layer application.
    """
    selected, positions, accepted = [], [], []
    counts, sector_counts, bytes_peak, errors = [], [], 0, 0
    first, cycles = None, 0
    begun = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        while cycles < requests or time.monotonic()-begun < seconds:
            # Time moves forward, backward and returns; fixed camera regions move.
            at = ['2020-01-01T00:00:00Z', '2020-07-01T00:00:00Z',
                  '2020-01-01T00:00:00Z', '2021-01-01T00:00:00Z'][cycles % 4]
            x, radius = [(0, 400000), (20000000, 400000),
                         (-1000000000000, 1), (30000000, 400000)][cycles % 4]
            started = time.perf_counter()
            response = fetch(base, query(at, x, radius))
            manifest = payload(response)
            selected.append(response['ms'])
            sectors = manifest['sectors']
            sector_counts.append(len(sectors))
            assert len(sectors) <= BUDGETS['sectors'], len(sectors)
            params = dict(at=at, revision=manifest['revision'])
            if 'temporal_revision' in manifest:
                params['temporal_revision'] = manifest['temporal_revision']
            paths = ['/api/positions/v1/sectors/'+quote(s['id'], safe='')+'?'+urlencode(params)
                     for s in sectors]
            frames = list(pool.map(lambda path: fetch(base, path), paths))
            members = 0
            for sector, result in zip(sectors, frames):
                body = payload(result)
                positions.append(result['ms'])
                bytes_peak = max(bytes_peak, len(result['body']))
                assert len(result['body']) <= BUDGETS['response_bytes']
                assert body['sector'] == sector['id']
                assert body['revision'] == manifest['revision']
                assert body['registry_revision'] == manifest['registry_revision']
                assert body['jd_tdb'] == manifest['jd_tdb']
                assert body['evaluated_at'] == manifest['evaluated_at']
                assert len(body['objects']) <= BUDGETS['sector_members']
                members += len(body['objects'])
            assert members <= BUDGETS['members']
            counts.append(members)
            elapsed = (time.perf_counter()-started)*1000
            accepted.append(elapsed)
            if first is None:
                first = elapsed
            cycles += 1
    # Explicit dense broad-phase overflow must fail without silently clipping.
    overflow = fetch(base, query('2020-01-01T00:00:00Z', 0, 1e13))
    assert overflow['status'] == 413, overflow
    return dict(cycles=cycles, duration_s=time.monotonic()-begun,
                selection_http_ms=distribution(selected), positions_http_ms=distribution(positions),
                driver_assembly_ms=distribution(accepted), first_driver_frame_ms=first,
                resident_min=min(counts), resident_max=max(counts),
                candidate_sector_counts=distribution(sector_counts),
                response_max_bytes=bytes_peak, errors=errors, dense_overflow_status=413)


def merge_report(directory, browser_paths, output):
    report = json.loads((directory/'physical_streaming_report.json').read_text())
    for name in ('host', 'verification'):
        path = directory/f'{name}.json'
        if path.exists():
            report[name] = json.loads(path.read_text())
    report['budgets'].update(accepted_p95_ms=500, accepted_p99_ms=1500, render_callback_cpu_p95_ms=16.8)
    for size in report['sizes']:
        count = size['count']
        size.update(known_count=count-count//128, unknown_count=count//128,
                    candidate_sector_count_range=[0, 16], fixture_sector_count=(count+127)//128)
        path = directory/f'temporal-{count}.sqlite'
        with sqlite3.connect(path) as db:
            size['fixture_metadata'] = {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM metadata')
                                        if k != 'coordinates'}
        with path.open('rb') as stream:
            size['fixture_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
        phases = directory/f'build-phases-{count}.json'
        if phases.exists():
            size['build_phases'] = json.loads(phases.read_text())
    for path in browser_paths:
        browser = json.loads(path.read_text())
        size = next(s for s in report['sizes'] if s['count'] == browser['count'])
        size['browser'] = browser
        metrics = browser['metrics']
        size['browser_diagnostic_passed'] = (
            metrics['accepted_frame_ms']['p95'] <= 500 and metrics['accepted_frame_ms']['p99'] <= 1500
            and metrics['frame_cpu_ms']['p95'] <= 16.8)
    report['required_limits_passed'] = all(s.get('browser', {}).get('complete', False)
        and all(s['browser']['checks'].values()) for s in report['sizes'])
    report['measured_diagnostics_passed'] = report['diagnostic_passed'] and all(
        s.get('browser_diagnostic_passed', False) for s in report['sizes'])
    report['unverified_diagnostics'] = ['Full per-frame main-thread CPU budget including asynchronous tasks; only render callback and separate task metrics measured.']
    report['initial_exploration'] = []
    for count in (100000, 1000000):
        path = directory/f'initial-browser-{count}.json'
        if path.exists():
            initial = json.loads(path.read_text())
            report['initial_exploration'].append(dict(count=count,
                source_scope='earlier implementation/build; retained outliers, not final acceptance',
                first_usable_scene_ms=initial.get('first_usable_scene_ms'),
                longtask_ms=initial['metrics'].get('longtask_ms'),
                raf_interval_ms=initial['metrics'].get('raf_interval_ms')))
    report['limitations'] = [
        'Only five existing DE440s body centers are real astronomy; million-row scaling is explicitly synthetic affine data.',
        'Real candidate lane is unconditional five; synthetic broad-phase permits false positives and rejects >16 candidates even if exact sphere would contain fewer.',
        'Three process/application-cold repeats, OS page cache unchanged; shared host without CPU isolation, concurrent builds/coverage/Chrome occurred.',
        'Server budgets are compared to stricter end-to-end HTTP wall times. Driver assembly does not measure browser acceptance.',
        'Render callback CPU measures layer.tick+renderer.render submission; asynchronous decode/merge/apply and all-run longtasks are separate.',
        'SwiftShader proves functional WebGL only; neither hardware60fps, monitor presentation nor GPU driver memory is measured.',
        'Heap samples cover whole Chrome tab; renderer.info counts and allocated attribute bytes are not GPU driver RSS.',
        'Finite180s backend and120s browser windows plus resource cycles support this workload, not asymptotic bounded memory or all workloads.',
        'Fixture/index construction/integrity/publication are O(N); no full catalog copy/hash occurs in temporal query path.',
    ]
    sources = ['backend/position_api.py', 'backend/temporal_api.py', 'data/temporal_index.py',
               'frontend/src/physical/sectorManager.js', 'frontend/src/physical/useVerifiedFrame.js',
               'tests/benchmark_temporal_streaming.py', 'tests/benchmark_temporal_streaming.mjs',
               'tests/temporal_provider.py', 'docs/PHYSICAL_STREAMING.md']
    report['final_source_sha256'] = {p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sources}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--counts', nargs='+', type=int, default=[100000, 1000000])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--requests', type=int, default=96)
    parser.add_argument('--seconds', type=float, default=180)
    parser.add_argument('--directory', type=Path, default=Path('/reports'))
    parser.add_argument('--build-only', type=Path)
    parser.add_argument('--count', type=int)
    parser.add_argument('--merge-browser', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, default=Path('docs/reports/physical_streaming_report.json'))
    args = parser.parse_args()
    if args.merge_browser:
        merge_report(args.directory, args.merge_browser, args.output)
        return
    if args.build_only:
        from data.temporal_index import build_synthetic
        started = time.perf_counter()
        metrics = {}
        build_synthetic(args.build_only, args.count, metrics=metrics)
        print(json.dumps(dict(seconds=time.perf_counter()-started,
                              builder_peak_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                              bytes=args.build_only.stat().st_size, phases=metrics)))
        return
    args.directory.mkdir(parents=True, exist_ok=True)
    report = dict(version='temporal-streaming-report/1', timestamp=datetime.now(timezone.utc).isoformat(),
                  budgets=BUDGETS, environment=dict(platform=platform.platform(), python=sys.version,
                    sqlite=importlib.import_module('sqlite3').sqlite_version,
                    packages={n:importlib.metadata.version(n) for n in ['fastapi','uvicorn','skyfield','numpy']}),
                  method=dict(cold='fresh process/application cache; OS page cache untouched',
                    rss='backend /proc RSS/HWM every50ms; generator/driver separate processes',
                    windows='three process repeats; final repeat sustained; fixed origins; four HTTP sector workers',
                    timing='HTTP client wall latency; driver assembly is not browser frame acceptance',
                    complexity='fixture/index construction/hash/integrity/publication O(N), excluded from request timings'),
                  sizes=[])
    target = args.directory/'physical_streaming_report.json'
    for count in args.counts:
        path = args.directory/f'temporal-{count}.sqlite'
        build = subprocess.run([sys.executable, '-m', 'tests.benchmark_temporal_streaming',
            '--build-only', str(path), '--count', str(count)], capture_output=True, text=True, check=True)
        size = dict(count=count, build=json.loads(build.stdout.strip().splitlines()[-1]), runs=[])
        report['sizes'].append(size)
        for repeat in range(args.repeats):
            with server(path) as (base, pid, samples, ready, health):
                assert health['objects'] == count, health
                baseline = rss(pid)['VmRSS']/1024
                outcome = exercise(base, args.requests, args.seconds if repeat == args.repeats-1 else 0)
                time.sleep(.1)
                tail = [s[1]/1024 for s in samples if s[0] >= time.monotonic()-min(60, outcome['duration_s']/2)]
                outcome.update(repeat=repeat, ready_s=ready, baseline_rss_mib=baseline,
                    peak_rss_mib=max(max(s[1],s[2]) for s in samples)/1024,
                    post_rss_mib=rss(pid)['VmRSS']/1024,
                    late_rss_min_mib=min(tail), late_rss_max_mib=max(tail),
                    rss_samples=len(samples))
                size['runs'].append(outcome)
                print(json.dumps(dict(count=count, **outcome)), flush=True)
            target.write_text(json.dumps(report, indent=2)+'\n')
    report['driver_peak_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    report['diagnostic_passed'] = all(
        r['selection_http_ms']['p95'] <= BUDGETS['selection_p95_ms']
        and r['selection_http_ms']['p99'] <= BUDGETS['selection_p99_ms']
        and r['positions_http_ms'].get('p95', 0) <= BUDGETS['positions_p95_ms']
        and r['positions_http_ms'].get('p99', 0) <= BUDGETS['positions_p99_ms']
        and r['peak_rss_mib'] <= BUDGETS['backend_peak_mib']
        and r['late_rss_max_mib']-r['late_rss_min_mib'] <= BUDGETS['late_growth_mib']
        for s in report['sizes'] for r in s['runs'])
    target.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
