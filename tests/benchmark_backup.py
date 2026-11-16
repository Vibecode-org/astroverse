"""Isolated Linux backup/restore cost, fresh child per operation.

Synthetic fixture preparation is excluded. Output records O(N) phases, Linux
process peak RSS, and extra allocated-file bytes sampled every 10ms. No page
cache flush or CPU isolation; one run per size is not a latency distribution.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time


def allocated(root):
    total = 0
    for path in root.rglob('*'):
        try:
            if path.is_file():
                total += path.stat().st_blocks * 512
        except FileNotFoundError:
            pass
    return total


def operation(action, source, target):
    from data.catalog_backup import backup_database, restore_database
    metrics = {}
    before = allocated(source.parent)
    peak = [before]
    stop = threading.Event()

    def sample():
        while not stop.wait(.01):
            peak[0] = max(peak[0], allocated(source.parent))

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    start = time.perf_counter()
    try:
        if action == 'backup':
            result = backup_database(source, target, metrics=metrics)
        else:
            result = restore_database(source, target, metrics=metrics)
    finally:
        elapsed = time.perf_counter() - start
        peak[0] = max(peak[0], allocated(source.parent))
        stop.set()
        thread.join()
    return dict(action=action, wall_seconds=elapsed, metrics=metrics,
                peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
                baseline_allocated_bytes=before,
                extra_peak_allocated_bytes=max(0, peak[0]-before),
                final_allocated_bytes=allocated(source.parent), result=str(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, choices=(100000, 1000000))
    parser.add_argument('--operation', choices=('backup', 'restore'))
    parser.add_argument('--source', type=Path)
    parser.add_argument('--target', type=Path)
    args = parser.parse_args()
    if not Path('/.dockerenv').exists():
        parser.error('run inside disposable Linux container')
    if args.operation:
        print(json.dumps(operation(args.operation, args.source, args.target), sort_keys=True))
        return
    if not args.count:
        parser.error('--count required')
    from tests.benchmark_incremental import records
    from data.streaming_catalog import build_streaming_index
    from data.bootstrap_catalog import sha256_file
    from data.incremental_catalog import publish_changes
    from data.runtime_catalog import DiskCatalog
    with tempfile.TemporaryDirectory(prefix='backup-benchmark-') as folder:
        root = Path(folder)
        working, bundle, restored = root/'working.sqlite', root/'backup', root/'restored.sqlite'
        metadata = build_streaming_index(working, None, objects=records(args.count), max_objects=256)
        changed = next(records(args.count))
        changed['description'] = 'Published patch preserved by backup'
        metadata = publish_changes(working, expected_revision=metadata['catalog_revision'], upserts=[changed])
        source_hash = sha256_file(working)
        results = []
        for action, source, target in [('backup', working, bundle), ('restore', bundle, restored)]:
            output = subprocess.check_output([sys.executable, '-m', 'tests.benchmark_backup',
                '--operation', action, '--source', str(source), '--target', str(target)], text=True)
            results.append(json.loads(output))
        assert sha256_file(restored) == source_hash
        with DiskCatalog(restored).snapshot() as snapshot:
            assert snapshot.object(changed['id']) == changed
            assert snapshot.metadata == metadata
        files = ['data/catalog_backup.py','data/bootstrap_catalog.py','data/runtime_catalog.py',
                 'tests/benchmark_backup.py']
        print(json.dumps(dict(count=args.count, sqlite_bytes=working.stat().st_size,
            sha256=source_hash, revision=metadata['catalog_revision'], operations=results,
            environment=dict(python=sys.version, sqlite=sqlite3.sqlite_version,
                             platform=platform.platform(), cpu_count=os.cpu_count()),
            source_sha256={name:sha256_file(name) for name in files},
            limitations=['one run per size', 'warm page cache', 'no CPU isolation',
                         'disk sampling may miss short transients',
                         'catalog preparation and patch excluded']), sort_keys=True))


if __name__ == '__main__':
    main()
