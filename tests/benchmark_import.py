"""Real HTTP import benchmark. Linux Docker only; isolated importer per size.

Predeclared acceptance: RSS <=384 MiB, 1m-100k <=64 MiB; total time
<=300/1800 s, peak allocated disk <=1/10 GiB. No full source file/list.
Sample named files AND importer open/unlinked /proc/PID/fd files every 20 ms;
count each inode once. This includes SQLite/VACUUM/legacy spools, old DB,
and source staging. Sampling can miss short peaks; not filesystem-wide usage.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import tempfile
import threading
import time

from tests.sbdb_fixture import serve

BUDGETS = {'rss_bytes': 384*1024**2, 'rss_growth_bytes': 64*1024**2,
           'seconds': {'100000': 300, '1000000': 1800},
           'peak_disk_bytes': {'100000': 1024**3, '1000000': 10*1024**3}}


def worker(path, url, count):
    from data.streaming_catalog import build_streaming_index
    from data.import_sbdb import import_sbdb
    meta = build_streaming_index(path, None, objects=iter([dict(id='sun', name='Sun', kind='star', scale='solar')]))
    import importlib
    memory = {}
    def rss():
        fields = {line.split(':')[0]: line.split(':')[1].strip() for line in Path('/proc/self/status').read_text().splitlines()}
        return {key: int(fields[key].split()[0])*1024 for key in ('VmRSS', 'VmHWM')}
    def observe(module, name):
        original = getattr(module, name)
        def observed(*args, **kwargs):
            before = rss()
            result = original(*args, **kwargs)
            memory[name] = {'before': before, 'after': rss()}
            return result
        setattr(module, name, observed)
    importer = importlib.import_module('data.import_sbdb')
    observe(importer, 'read_response')
    observe(importer, 'build_streaming_index')
    observe(importer, 'validate_staged')
    observe(importlib.import_module('data.streaming_catalog'), 'write_representations')
    start = time.perf_counter()
    result = import_sbdb(path, expected_revision=meta['catalog_revision'], url=url, limit=count,
                         total_timeout=3600, mode='fixture')
    return {'count': count, 'memory_checkpoints': memory, 'elapsed_seconds': time.perf_counter()-start,
            'rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'database_bytes': path.stat().st_size, 'input': result['input'],
            'revision': result['metadata']['catalog_revision'], 'metrics': result['metrics']}


def sample_disk(pid, root):
    seen = set()
    total = staging = 0
    paths = list(root.rglob('*')) + list(Path(f'/proc/{pid}/fd').glob('*'))
    for path in paths:
        try:
            st = path.stat()
            if not path.is_file() or (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            size = st.st_blocks*512
            total += size
            if '.import-' in str(path):
                staging += size
        except OSError:
            pass
    return total, staging


def measure(count):
    with tempfile.TemporaryDirectory() as tmp, serve(count) as (url, _):
        root = Path(tmp)
        path = root/'catalog.sqlite'
        peak = staging = samples = 0
        # Avoid PIPE backpressure: worker only emits one small final JSON.
        process = subprocess.Popen([sys.executable, '-m', 'tests.benchmark_import', '--worker', str(path),
                                    '--url', url, '--count', str(count)], stdout=subprocess.PIPE, text=True)
        while process.poll() is None:
            disk, stage = sample_disk(process.pid, root)
            peak, staging = max(peak, disk), max(staging, stage)
            samples += 1
            time.sleep(.02)
        output, _ = process.communicate()
        if process.returncode:
            raise RuntimeError(f'import worker exited {process.returncode}')
        result = json.loads(output)
        result.update(peak_allocated_disk_bytes=peak, peak_named_staging_bytes=staging, samples=samples)
        # Production uvicorn/TCP against the imported file, with no objects.json.
        from tests.import_http import check_catalog_http
        result['http'] = check_catalog_http(path, count+1)
        result['passed'] = (result['rss_bytes'] <= BUDGETS['rss_bytes'] and
                            result['elapsed_seconds'] <= BUDGETS['seconds'][str(count)] and
                            peak <= BUDGETS['peak_disk_bytes'][str(count)])
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--url')
    parser.add_argument('--count', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker, args.url, args.count)), flush=True)
        return
    report = {'method': {'baseline_objects': 1, 'sample_interval_ms': 20,
              'rss_scope': 'isolated importer including SQLite; fixture/API separate',
              'disk_scope': 'named files and importer open/unlinked files, allocated blocks, unique inodes',
              'workload': 'synthetic SBDB rows, one solar family; backend/browser checks may run concurrently'},
              'budgets': BUDGETS, 'environment': {'platform': platform.platform(), 'python': sys.version,
              'sqlite': __import__('sqlite3').sqlite_version, 'cpus': os.cpu_count(),
              'cgroup_memory_max': Path('/sys/fs/cgroup/memory.max').read_text().strip(),
              'cgroup_cpu_max': Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
              'cpu_isolation': False}, 'results': []}
    for count in [100000, 1000000]:
        result = measure(count)
        report['results'].append(result)
        print(json.dumps(result), flush=True)
    report['rss_growth_bytes'] = report['results'][1]['rss_bytes']-report['results'][0]['rss_bytes']
    report['passed'] = all(row['passed'] for row in report['results']) and report['rss_growth_bytes'] <= BUDGETS['rss_growth_bytes']
    if args.output:
        args.output.write_text(json.dumps(report, indent=2)+'\n')
    if not report['passed']:
        raise SystemExit('import budgets failed')


if __name__ == '__main__':
    main()
