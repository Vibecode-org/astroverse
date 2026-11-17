"""Isolated SQLite/API load acceptance. No ordinary stack or volume is touched.

python -m tests.benchmark_api_load --report docs/reports/api_load_report.json
Cold means fresh backend process/cache, never a flushed OS page cache.
"""
import argparse
from datetime import datetime, timezone
import platform
import sqlite3
import importlib.metadata
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

BUDGETS = dict(bounded_p95_ms=500, bounded_p99_ms=1500,
               request_max_ms=10000, worker_peak_mib=512,
               plateau_growth_mib=32, ready_seconds=60,
               page_bytes=2*1024*1024, page_objects=512,
               search_objects=500, filtered_bytes=8*1024*1024,
               fixture_seconds=300, writer_seconds=180)
ROOT = Path(__file__).resolve().parents[1]
NEAR = '/api/spatial/v1/nearby?scale=local&frame=equatorial&x=1&y=0&z=0&radius=4'


def records(count):
    """Reuse writer fixture schema, replace distribution; all rows synthetic."""
    from tests.benchmark_incremental import records as base_records
    third = count//3
    for i, row in enumerate(base_records(count)):
        if i < third:
            group = 'dense'
            if 'parent' not in row:
                row.update(ra=0, dec=0, distance_ly=1)
        elif i < 2*third:
            group = 'sparse'
            if 'parent' not in row:
                row.update(ra=0, dec=0, distance_ly=1000+(i//10)*64)
        else:
            group = 'large_family'
            row.pop('ra', None)
            row.pop('dec', None)
            row.pop('distance_ly', None)
            row['kind'] = 'exoplanet'
            row['parent'] = 'bench_0000000'
        if i >= count-3:
            row.pop('parent', None)
            row.pop('ra', None)
            row.pop('dec', None)
            row.pop('distance_ly', None)
            row['kind'] = 'star'
            group = 'edge_unknown'
            if i == count-3:
                row.update(ra=0, dec=0, distance_ly=0)
                group = 'edge_zero'
            elif i == count-2:
                row['kind'] = 'exoplanet'
                row['parent'] = f'bench_{count-1:07d}'
        # Group labels are searchable without inventing physical positions.
        row['description'] = group
        if i == 0:
            row['description'] += ' Уникальная Земля'
        yield row


def digest_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rss(pid):
    path = Path(f'/proc/{pid}/status')
    if not path.exists():
        return None
    return {line.split(':')[0]: int(line.split()[1]) for line in path.read_text().splitlines()
            if line.startswith(('VmRSS:', 'VmHWM:'))}


def fetch(base, path, headers=None):
    started = time.perf_counter()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(base+path, headers=headers or {})
    try:
        response = opener.open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read()
        return dict(status=response.code, body=body, headers={key.lower(): value for key, value in response.headers.items()},
                    ms=(time.perf_counter()-started)*1000)


def payload(response):
    assert response['status'] == 200, (response['status'], response['body'][:300])
    return json.loads(response['body'])


@contextmanager
def server(path, count):
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    base = f'http://127.0.0.1:{port}'
    env = {**os.environ, 'ASTROVERSE_CATALOG_MODE': 'published',
           'ASTROVERSE_SECTOR_PATH': str(path), 'ASTROVERSE_CATALOG_PATH': '',
           'ASTROVERSE_RATE_OBJECTS': '0', 'ASTROVERSE_RATE_SEARCH': '0'}
    with tempfile.TemporaryFile() as logs:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app:app',
                                    '--host', '127.0.0.1', '--port', str(port),
                                    '--no-access-log'], cwd=ROOT, env=env,
                                   stdout=logs, stderr=logs)
        started = time.perf_counter()
        peak = [0]
        stopped = threading.Event()
        def sample():
            while not stopped.wait(.02):
                value = rss(process.pid)
                if value:
                    peak[0] = max(peak[0], value['VmRSS'], value.get('VmHWM', 0))
        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        try:
            while time.perf_counter()-started < BUDGETS['ready_seconds']:
                if process.poll() is not None:
                    logs.seek(0)
                    raise RuntimeError(logs.read().decode()[-4000:])
                try:
                    assert payload(fetch(base, '/api/health'))['objects'] == count
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(.03)
            else:
                raise RuntimeError('backend readiness deadline')
            yield base, process.pid, peak, time.perf_counter()-started
        finally:
            stopped.set()
            sampler.join()
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered)*fraction)-1)], 3)


def window(base, paths, concurrency, requests, raw=False):
    start = time.perf_counter()
    def call(i):
        name, path = list(paths.items())[i % len(paths)]
        response = fetch(base, path)
        data = payload(response)
        if name == 'page':
            assert len(data['objects']) <= BUDGETS['page_objects']
            assert len(response['body']) <= BUDGETS['page_bytes']
        elif name.startswith('search'):
            assert len(data) <= BUDGETS['search_objects']
        elif name == 'object':
            assert data['id'] == 'bench_0000000'
        return name, response['ms'], len(response['body'])
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(call, range(requests)))
    seconds = time.perf_counter()-start
    measurements = {}
    for name in paths:
        values = [ms for endpoint, ms, _ in results if endpoint == name]
        if values:
            measurements[name] = dict(n=len(values), p50_ms=percentile(values, .5),
                                      p95_ms=percentile(values, .95), p99_ms=percentile(values, .99),
                                      max_ms=round(max(values), 3),
                                      max_bytes=max(size for endpoint, _, size in results if endpoint == name))
    result = dict(seconds=round(seconds, 4), requests=len(results),
                  requests_per_second=round(len(results)/seconds, 3), endpoints=measurements)
    if raw:
        result['_values'] = results
    return result


def sustained(base, pid, peak, paths, duration):
    start = time.perf_counter()
    values = {name: [] for name in paths}
    requests, cycles, memory = 0, 0, []
    while time.perf_counter()-start < duration:
        result = window(base, paths, 16, 128, raw=True)
        for name, ms, _ in result['_values']:
            values[name].append(ms)
        requests += result['requests']
        cycles += 1
        current = rss(pid)
        if current:
            peak[0] = max(peak[0], current['VmRSS'], current.get('VmHWM', 0))
        memory.append(current)
    elapsed = time.perf_counter()-start
    endpoints = {name: dict(n=len(items), p50_ms=percentile(items, .5),
                           p95_ms=percentile(items, .95), p99_ms=percentile(items, .99),
                           max_ms=round(max(items), 3)) for name, items in values.items()}
    # Retain at most six representative RSS samples in compact permanent report.
    late = memory[len(memory)//2:]
    growth = None if any(item is None for item in late) else (max(item['VmRSS'] for item in late)-min(item['VmRSS'] for item in late))/1024
    result = dict(concurrency=16, requested_seconds=duration, seconds=round(elapsed, 3),
                  cycles=cycles, requests=requests, requests_per_second=round(requests/elapsed, 3),
                  endpoints=endpoints, rss_samples_kib=[memory[round(i*(len(memory)-1)/5)] for i in range(6)],
                  late_window_rss_range_mib=growth, peak_mib=peak[0]/1024 if growth is not None else None)
    result['passed'] = (growth is not None and growth <= BUDGETS['plateau_growth_mib'] and result['peak_mib'] <= BUDGETS['worker_peak_mib'] and all(item['p95_ms'] <= BUDGETS['bounded_p95_ms'] and item['p99_ms'] <= BUDGETS['bounded_p99_ms'] and item['max_ms'] <= BUDGETS['request_max_ms'] for item in endpoints.values()))
    return result


def contracts(base, revision, path, count, full_pagination=False):
    checks = {}
    located = payload(fetch(base, '/api/spatial/v1/objects/bench_0000000/sector'))
    sid = located['sector']['id']
    page_path = '/api/spatial/v1/sectors/'+urllib.parse.quote(sid, safe='')
    first = fetch(base, page_path+'?limit=512')
    page = payload(first)
    ids = [item['object']['id'] for item in page['objects']]
    assert len(ids) == len(set(ids)) and len(ids) <= 512
    assert first['headers'].get('x-catalog-snapshot') == revision
    after = page['next_after']
    assert after, 'large family must require pagination'
    second = payload(fetch(base, page_path+'?limit=512&after='+urllib.parse.quote(after)))
    second_ids = [item['object']['id'] for item in second['objects']]
    assert not set(ids).intersection(second_ids)
    checks['pagination_distinct_two_pages'] = True
    if full_pagination:
        from data.runtime_catalog import DiskCatalog
        from data.coordinates import snapshot_coordinates
        traversed, pages, cursor = 0, 0, None
        with DiskCatalog(path).snapshot() as snapshot:
            expected = iter(snapshot.select(sector=sid))
            while True:
                route = page_path+'?limit=512&snapshot='+revision
                if cursor is not None:
                    route += '&after='+urllib.parse.quote(cursor, safe='')
                response = fetch(base, route)
                actual = payload(response)
                assert len(response['body']) <= BUDGETS['page_bytes']
                assert len(actual['objects']) <= 512
                for card in actual['objects']:
                    wanted = next(expected)
                    assert card['object'] == wanted
                    assert card['coordinates'] == snapshot_coordinates(wanted)
                    assert all(card['coordinates'][key] is None for key in
                               ('simulation_position', 'reference_system', 'source_epoch', 'time_scale', 'accuracy'))
                    if wanted.get('parent'):
                        assert card['coordinates']['position'] is None
                    traversed += 1
                pages += 1
                next_cursor = actual['next_after']
                if next_cursor is None:
                    assert next(expected, None) is None
                    break
                assert next_cursor != cursor and actual['objects']
                cursor = next_cursor
        checks['full_pagination_exact_sqlite_cards_coordinates_order'] = True
        checks['full_pagination_objects'] = traversed
        checks['full_pagination_pages'] = pages
    etag = first['headers']['etag']
    for condition in (etag, 'W/'+etag, '"unrelated", W/'+etag, '*'):
        response = fetch(base, page_path+'?limit=512', {'If-None-Match': condition})
        assert response['status'] == 304 and response['body'] == b''
    checks['etag_variants_empty_304'] = True
    errors = {page_path+'?limit=513': 422, page_path+'?snapshot=stale': 409,
              page_path+'?at=2026-01-01': 422,
              '/api/objects/missing-benchmark-object': 404,
              '/api/spatial/v1/sectors/nonexistent': 404,
              NEAR+'&radius=-1': 422,
              '/api/objects?q=dense': 413}
    for path, status in errors.items():
        assert fetch(base, path, {'If-None-Match': '*'})['status'] == status, path
    checks['validation_404_409_413_422_before_conditionals'] = True
    cyrillic = payload(fetch(base, '/api/search?q='+urllib.parse.quote('Уникальная Земля')))
    assert [row['id'] for row in cyrillic] == ['bench_0000000']
    checks['percent_encoded_cyrillic'] = True
    for index in (count-3, count-2, count-1):
        located_edge = payload(fetch(base, f'/api/spatial/v1/objects/bench_{index:07d}/sector'))
        coords = located_edge['coordinates']
        assert coords['simulation_position'] is None
        assert coords['position'] == ([0.0, 0.0, 0.0] if index == count-3 else None)
    checks['unknown_child_and_zero_coordinates'] = True
    checks['filtered_exact_object'] = payload(fetch(base, '/api/objects?q=Уникальная'.replace('Уникальная', urllib.parse.quote('Уникальная'))))[0]['id'] == 'bench_0000000'
    paths = workload_paths(sid, count)
    return checks, paths


def workload_paths(sid, count=None):
    sparse_x = 1000+(((count//3+9)//10)*10//10)*64 if count else 1000
    return dict(nearby_dense=NEAR,
                nearby_empty='/api/spatial/v1/nearby?scale=local&frame=equatorial&x=-1000&y=0&z=0&radius=0',
                nearby_sparse=f'/api/spatial/v1/nearby?scale=local&frame=equatorial&x={sparse_x}&y=0&z=0&radius=32',
                page='/api/spatial/v1/sectors/'+urllib.parse.quote(sid, safe='')+'?limit=512',
                search='/api/search?q=dense', search_no_match='/api/search?q=absent_very_last_scan',
                locate='/api/spatial/v1/objects/bench_0000000/sector',
                object='/api/objects/bench_0000000')


def publication_checks(path, count, base, revision):
    """Isolated publication under active HTTP readers; no live volume accesses."""
    from data.incremental_catalog import publish_changes
    from data.publication import RevisionConflict
    from data.runtime_catalog import DiskCatalog
    # A sparse family is bounded; the intentionally giant family is not patched.
    sparse_i = ((count//3+9)//10)*10
    oid = f'bench_{sparse_i:07d}'
    with DiskCatalog(path).snapshot() as old:
        changed = dict(old.object(oid), description='published benchmark update')
        old_row = old.object(oid)
        sid = old.locate(oid)
        route = '/api/spatial/v1/sectors/'+urllib.parse.quote(sid, safe='')+'?limit=512'
        before_page = fetch(base, route+'&snapshot='+revision)
        expected_page = payload(before_page)
        old_etag = before_page['headers']['etag']
        checks = {}
        original_sha = digest_file(path)
        # Failure during compatibility generation must leave publication bytes intact.
        with patch('data.incremental_catalog.write_catalog_representations', side_effect=RuntimeError('injected')):
            try:
                publish_changes(path, expected_revision=revision, upserts=[changed])
                raise AssertionError('injected failure did not propagate')
            except RuntimeError as exc:
                assert str(exc) == 'injected'
        assert digest_file(path) == original_sha
        checks['failed_writer_preserves_bytes'] = True
        stop = threading.Event()
        reads, read_errors, pinned_statuses = [], [], []
        def reader():
            try:
                while not stop.is_set():
                    response = fetch(base, '/api/objects/'+oid)
                    reads.append(payload(response)['description'])
                    pinned = fetch(base, route+'&snapshot='+revision)
                    pinned_statuses.append(pinned['status'])
                    assert pinned['status'] in (200, 409)
                    if pinned['status'] == 200:
                        assert payload(pinned) == expected_page
            except Exception as exc:
                read_errors.append(repr(exc))
        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        metrics = {}
        started = time.perf_counter()
        try:
            # Two writers pin the same revision; exactly one can publish.
            def writer(_):
                try:
                    local_metrics = {}
                    result = publish_changes(path, expected_revision=revision, upserts=[changed], metrics=local_metrics)
                    metrics.update(local_metrics)
                    return result['catalog_revision']
                except RevisionConflict:
                    return 'conflict'
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(writer, range(2)))
        finally:
            stop.set()
            thread.join(timeout=35)
        assert results.count('conflict') == 1
        new_revision = next(value for value in results if value != 'conflict')
        assert new_revision != revision and old.object(oid) == old_row
        assert not thread.is_alive() and not read_errors, read_errors
        assert reads and set(reads) <= {old_row['description'], changed['description']}
        assert payload(fetch(base, '/api/objects/'+oid))['description'] == changed['description']
        assert fetch(base, route+'&snapshot='+revision, {'If-None-Match': old_etag})['status'] == 409
        restarted = fetch(base, route+'&snapshot='+new_revision)
        assert restarted['headers']['x-catalog-snapshot'] == new_revision
        assert next(card['object'] for card in payload(restarted)['objects'] if card['object']['id'] == oid) == changed
        assert pinned_statuses
        checks['pinned_pages_consistent_or_409_and_restart'] = True
        assert fetch(base, NEAR+'&snapshot='+revision, {'If-None-Match': '*'})['status'] == 409
        checks.update(concurrent_writer_conflict=True, atomic_http_readers=True,
                      old_reader_retains_inode=True, stale_snapshot_rejected=True)
        return dict(checks=checks, reader_requests=len(reads),
                    writer_seconds=round(time.perf_counter()-started, 3),
                    revision=new_revision, metrics=metrics)


def run(args):
    from data.streaming_catalog import build_streaming_index
    report = dict(version='api-load/1', created_utc=datetime.now(timezone.utc).isoformat(),
                  environment=dict(platform=platform.platform(), python=sys.version, sqlite=sqlite3.sqlite_version,
                                   cpu_count=os.cpu_count(), packages={name: importlib.metadata.version(name) for name in ('fastapi', 'uvicorn', 'starlette')},
                                   source_sha256={name: digest_file(ROOT/name) for name in ('tests/benchmark_api_load.py', 'backend/app.py', 'backend/catalog_responses.py', 'data/streaming_catalog.py', 'data/runtime_catalog.py', 'data/incremental_catalog.py', 'backend/sector_api.py', 'backend/byte_cache.py', 'data/sectors.py', 'tests/benchmark_incremental.py')}),
                  budgets_status='HTTP byte/object limits are contracts; latency/RSS/build/writer thresholds are proposed diagnostic checks, not accepted product SLA',
                  budgets=BUDGETS, matrix=dict(counts=args.counts,
                  concurrency=args.concurrency, repeats=args.repeats, requests_per_window=args.requests,
                  warm_windows=args.windows, sustained_seconds=args.sustained_seconds), method=dict(cold='fresh backend process; health only before cold workload',
                  os_page_cache='not flushed', rss='Linux /proc child VmRSS/VmHWM, sampled every 20ms',
                  memory_growth='late-half warm-window RSS range heuristic, not proof of asymptotic plateau',
                  latency='client wall time incl body; nearest-rank percentiles; small tails are maxima',
                  rate_limits='disabled for isolated load; policy correctness belongs to API unit tests',
                  fixture='deterministic synthetic mixed dense/sparse/large family; no physical-scene claim',
                  full_legacy='excluded from bounded load matrix; known O(N) streaming'), runs=[], passed=False)
    try:
        for count in args.counts:
            with tempfile.TemporaryDirectory(prefix='astroverse-api-load-') as directory:
                path = Path(directory)/'catalog.sqlite'
                logical = hashlib.sha256()
                def fixture():
                    for row in records(count):
                        logical.update(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()+b'\n')
                        yield row
                started = time.perf_counter()
                meta = build_streaming_index(path, None, objects=fixture(), max_objects=256)
                fixture_seconds = time.perf_counter()-started
                generator_driver_rss = rss(os.getpid())
                group = dict(count=count, fixture=dict(logical_sha256=logical.hexdigest(),
                             sqlite_sha256=digest_file(path), sqlite_bytes=path.stat().st_size,
                             revision=meta['catalog_revision'], seconds=round(fixture_seconds, 3), generator_driver_rss_kib=generator_driver_rss), samples=[])
                report['runs'].append(group)
                for concurrency in args.concurrency:
                    for repeat in range(args.repeats):
                        with server(path, count) as (base, pid, peak, ready):
                            # Discover sector via SQL outside backend to avoid warming response caches.
                            from data.runtime_catalog import DiskCatalog
                            with DiskCatalog(path).snapshot() as snapshot:
                                sid = snapshot.locate('bench_0000000')
                            paths = workload_paths(sid, count)
                            baseline = rss(pid)
                            cold = window(base, paths, concurrency, args.requests)
                            checks, paths = contracts(base, meta['catalog_revision'], path, count, full_pagination=concurrency == args.concurrency[0] and repeat == 0)
                            warm, memory = [], []
                            for _ in range(args.windows):
                                warm.append(window(base, paths, concurrency, args.requests))
                                memory.append(rss(pid))
                            final = rss(pid)
                            driver_memory = rss(os.getpid())
                            if final:
                                peak[0] = max(peak[0], final['VmRSS'], final.get('VmHWM', 0))
                            growth = None if any(item is None for item in memory) else (max(item['VmRSS'] for item in memory[len(memory)//2:])-min(item['VmRSS'] for item in memory[len(memory)//2:]))/1024
                            item = dict(concurrency=concurrency, repeat=repeat, ready_seconds=round(ready, 3),
                                        cold=cold, warm=warm, rss_baseline_kib=baseline, rss_windows_kib=memory, rss_final_kib=final,
                                        peak_mib=peak[0]/1024 if final else None, driver_rss_kib=driver_memory,
                                        late_window_rss_range_mib=growth, checks=checks)
                            metrics = [endpoint for win in [cold]+warm for endpoint in win['endpoints'].values()]
                            item['passed'] = (all(checks.values()) and all(m['p95_ms'] <= BUDGETS['bounded_p95_ms'] and m['p99_ms'] <= BUDGETS['bounded_p99_ms'] and m['max_ms'] <= BUDGETS['request_max_ms'] for m in metrics)
                                              and item['peak_mib'] is not None and item['peak_mib'] <= BUDGETS['worker_peak_mib'] and growth <= BUDGETS['plateau_growth_mib'])
                            group['samples'].append(item)
                            print(json.dumps(dict(count=count, concurrency=concurrency, repeat=repeat, passed=item['passed'])), flush=True)
                with server(path, count) as (base, pid, peak, _):
                    with DiskCatalog(path).snapshot() as snapshot:
                        sid = snapshot.locate('bench_0000000')
                    group['sustained'] = sustained(base, pid, peak, workload_paths(sid, count), args.sustained_seconds)
                    group['publication'] = publication_checks(path, count, base, meta['catalog_revision'])
                group['passed'] = (fixture_seconds <= BUDGETS['fixture_seconds'] and all(item['passed'] for item in group['samples']) and group['sustained']['passed'] and all(group['publication']['checks'].values()) and group['publication']['writer_seconds'] <= BUDGETS['writer_seconds'])
        report['passed'] = all(group['passed'] for group in report['runs'])
    except Exception as exc:
        report['error'] = dict(type=type(exc).__name__, message=str(exc))
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


def verify_report(report_path):
    """Untimed supplemental oracles; retain original timing/source evidence."""
    from data.streaming_catalog import build_streaming_index
    report = json.loads(report_path.read_text())
    supplemental = dict(created_utc=datetime.now(timezone.utc).isoformat(),
                        source_sha256=digest_file(Path(__file__)),
                        method='untimed regenerated fixture; logical checksum matches original; raw SQL bounds clamp oracle independent of RTree/nearby implementation',
                        runs=[], passed=False)
    report['supplemental_verification'] = supplemental
    try:
        for group in report['runs']:
            count = group['count']
            with tempfile.TemporaryDirectory(prefix='astroverse-api-oracle-') as directory:
                path = Path(directory)/'catalog.sqlite'
                digest = hashlib.sha256()
                dense_expected, fixture_first = [], None
                def fixture():
                    nonlocal fixture_first
                    for row in records(count):
                        digest.update(json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()+b'\n')
                        if fixture_first is None:
                            fixture_first = row
                        if 'dense' in row.get('description', '').lower() and len(dense_expected) < 500:
                            dense_expected.append(dict(id=row['id'], name=row['name'], latin=row.get('latin') or '', kind=row['kind'], scale=row['scale']))
                        yield row
                metadata = build_streaming_index(path, None, objects=fixture(), max_objects=256)
                logical_sha = digest.hexdigest()
                assert logical_sha == group['fixture']['logical_sha256'], 'fixture logical checksum changed'
                assert metadata['catalog_revision'] == group['fixture']['revision'], 'fixture semantic revision changed'
                checks = dict(original_fixture_logical_checksum=True, original_semantic_revision=True)
                with sqlite3.connect(path) as db:
                    db.row_factory = sqlite3.Row
                    def nearby_oracle(center, radius):
                        result = []
                        for row in db.execute("SELECT * FROM sectors WHERE scale='local' AND frame='equatorial' AND min_x IS NOT NULL ORDER BY id"):
                            closest = [min(row['max_'+axis], max(row['min_'+axis], center[i])) for i, axis in enumerate('xyz')]
                            if math.dist(center, closest) <= radius:
                                result.append(dict(row))
                        return result
                    sparse_x = 1000+(((count//3+9)//10)*10//10)*64
                    queries = [('dense', (1, 0, 0), 4), ('sparse', (sparse_x, 0, 0), 32),
                               ('empty', (-1000, 0, 0), 0)]
                    with server(path, count) as (base, _, _, _):
                        for name, center, radius in queries:
                            expected = nearby_oracle(center, radius)
                            assert len(expected) <= 128
                            route = '/api/spatial/v1/nearby?'+urllib.parse.urlencode(dict(scale='local', frame='equatorial', x=center[0], y=center[1], z=center[2], radius=radius))
                            actual = payload(fetch(base, route))
                            assert actual['sectors'] == expected, name
                            assert actual['snapshot'] == metadata['catalog_revision']
                            if name == 'empty':
                                assert expected == []
                            else:
                                assert expected, name+' workload accidentally empty'
                            checks['nearby_'+name+'_exact_bounds_oracle'] = True
                        assert payload(fetch(base, '/api/search?q=dense')) == dense_expected
                        assert payload(fetch(base, '/api/search?q=absent_very_last_scan')) == []
                        checks['search_dense_exact_first500_and_empty'] = True
                        # Novel query costs remain separate from timed repeated-key
                        # matrix. Each query has a fixture-derived exact oracle.
                        churn = []
                        for i in range(16):
                            wanted = dense_expected[i]
                            for query, expected in ((wanted['name'], [wanted]), (f'absent_distinct_query_{i:04d}', [])):
                                response = fetch(base, '/api/search?'+urllib.parse.urlencode({'q': query}))
                                assert payload(response) == expected
                                churn.append(dict(query=query, status=response['status'], objects=len(expected), ms=round(response['ms'], 3)))
                        checks['distinct_search_queries_exact_content'] = True
                        assert payload(fetch(base, '/api/objects/bench_0000000')) == fixture_first
                        located = payload(fetch(base, '/api/spatial/v1/objects/bench_0000000/sector'))
                        sid = db.execute("SELECT sector_id FROM objects WHERE id='bench_0000000'").fetchone()[0]
                        expected_sector = dict(db.execute('SELECT * FROM sectors WHERE id=?', (sid,)).fetchone())
                        assert located['object_id'] == fixture_first['id']
                        assert located['snapshot'] == metadata['catalog_revision']
                        assert located['sector'] == expected_sector
                        coords = located['coordinates']
                        assert coords['position'] == [1.0, 0.0, 0.0] and coords['frame'] == 'equatorial'
                        assert coords['unit'] == 'ly' and coords['source'] == 'synthetic' and coords['status'] == 'synthetic'
                        assert all(coords[key] is None for key in ('simulation_position', 'reference_system', 'source_epoch', 'time_scale', 'accuracy', 'origin', 'evaluated_at'))
                        checks['raw_card_and_locate_exact_fixture_sector_coordinates'] = True
                        for route in (NEAR+'&at=2026-01-01',
                                      '/api/spatial/v1/objects/bench_0000000/sector?at=2026-01-01',
                                      NEAR+'&limit=0', NEAR+'&limit=129'):
                            assert fetch(base, route, {'If-None-Match': '*'})['status'] == 422
                        checks['nearby_locate_time_and_limit_validation_422'] = True
                        huge_expected = nearby_oracle((sparse_x, 0, 0), 1000000)
                        assert len(huge_expected) > 128, 'broad query must exceed sector budget'
                        route = '/api/spatial/v1/nearby?'+urllib.parse.urlencode(dict(scale='local', frame='equatorial', x=sparse_x, y=0, z=0, radius=1000000))
                        assert fetch(base, route, {'If-None-Match': '*'})['status'] == 413
                        checks['nearby_over128_413_before_conditional'] = True
                supplemental['runs'].append(dict(count=count, fixture_logical_sha256=logical_sha,
                                                 revision=metadata['catalog_revision'], broad_oracle_sectors=len(huge_expected),
                                                 distinct_search_queries=dict(method='32 distinct sequential cold query keys, exact fixture-derived match/no-match content; no latency SLA asserted; shared existing filtered8MiB response cache',
                                                                              samples=churn, p50_ms=percentile([item['ms'] for item in churn], .5), p95_ms=percentile([item['ms'] for item in churn], .95), max_ms=max(item['ms'] for item in churn)), checks=checks, passed=all(checks.values())))
                print(json.dumps(dict(supplemental_count=count, passed=True)), flush=True)
        supplemental['passed'] = bool(supplemental['runs']) and all(item['passed'] for item in supplemental['runs'])
    except Exception as exc:
        supplemental['error'] = dict(type=type(exc).__name__, message=str(exc))
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return supplemental


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-report', type=Path, help='Append untimed checksum-matched content oracles to an existing report')
    parser.add_argument('--counts', type=int, nargs='+', default=[100000, 1000000])
    parser.add_argument('--concurrency', type=int, nargs='+', default=[1, 4, 16])
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--requests', type=int, default=128)
    parser.add_argument('--sustained-seconds', type=float, default=60)
    parser.add_argument('--windows', type=int, default=6)
    parser.add_argument('--report', type=Path, default=Path('docs/reports/api_load_report.json'))
    args = parser.parse_args()
    if args.verify_report:
        if not verify_report(args.verify_report)['passed']:
            raise SystemExit(1)
        return
    if min(args.counts) < 15000 or min(args.concurrency) < 1 or min(args.repeats, args.windows) < 1 or args.requests < 8 or args.sustained_seconds <= 0:
        parser.error('counts >=15000, requests >=8 and positive matrix dimensions required')
    result = run(args)
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
