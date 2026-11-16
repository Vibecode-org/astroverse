"""Fixed-patch locality benchmark; run each size in a fresh Docker process.

Budgets are declared before measurements. Baseline uses the pre-sprint writer
and its full-builder metrics; optimized uses publish_changes(metrics=...).
All generated catalogs and publication artifacts are private and self-cleaning.
"""
import argparse
import hashlib
import json
from pathlib import Path
import resource
import tempfile
import threading
import time
from unittest.mock import patch


BUDGETS = {
    'local_seconds_max': 2.0,
    'local_growth_ratio_max': 3.0,
    'local_growth_allowance_seconds': 0.05,
    'normalized_records_max': 1,
    'affected_objects_max': 4096,
    'total_seconds_max': 180.0,
    'process_peak_rss_mib_max': 512,
}


def records(count):
    for i in range(count):
        row = dict(id=f'bench_{i:07d}', name=f'Synthetic {i:07d}',
                   kind='exoplanet' if i % 10 else 'star', scale='local',
                   source='synthetic', radius=1, color='#aaccee')
        if i % 10:
            row['parent'] = f'bench_{i-i%10:07d}'
        else:
            row.update(ra=0, dec=0,
                       distance_ly=1+(i//1000)*64+((i//10)%100)*0.1)
        yield row


def measure(count, baseline):
    import data.incremental_catalog as writer
    from data.runtime_catalog import DiskCatalog
    from data.streaming_catalog import build_streaming_index

    with tempfile.TemporaryDirectory(prefix='astroverse-incremental-') as tmp:
        path = Path(tmp)/'runtime.sqlite'
        build_metrics = {}
        meta = build_streaming_index(path, None, objects=records(count),
                                     max_objects=256, metrics=build_metrics)
        changed = next(records(count))
        changed['description'] = 'Изменённая карточка / fixed patch'
        metrics = {}
        done = threading.Event()
        disk_peak = [path.stat().st_size]

        def sample_disk():
            while not done.wait(0.05):
                try:
                    size = sum(p.stat().st_size for p in Path(tmp).rglob('*') if p.is_file())
                    disk_peak[0] = max(disk_peak[0], size)
                except FileNotFoundError:
                    pass

        sampler = threading.Thread(target=sample_disk, daemon=True)
        sampler.start()
        started = time.perf_counter()
        try:
            if baseline:
                def measured_builder(*args, **kwargs):
                    return build_streaming_index(*args, **kwargs, metrics=metrics)
                with patch.object(writer, 'build_streaming_index', measured_builder):
                    result = writer.publish_changes(path, expected_revision=meta['catalog_revision'], upserts=[changed])
                metrics['local_update_seconds'] = metrics['read_normalize_seconds']+metrics['index_seconds']
                metrics['normalized_records'] = count
            else:
                result = writer.publish_changes(path, expected_revision=meta['catalog_revision'], upserts=[changed], metrics=metrics)
            elapsed = time.perf_counter()-started
        finally:
            done.set()
            sampler.join()
        with DiskCatalog(path).snapshot() as snapshot:
            assert snapshot.metadata['object_count'] == count
            assert snapshot.object(changed['id']) == changed
            assert [row['id'] for row in snapshot.select(q='изменённая')] == [changed['id']]
            binary = {}
            for version in ('v1', 'v2'):
                digest = hashlib.sha256()
                for chunk in snapshot.binary(version):
                    digest.update(chunk)
                binary[version] = digest.hexdigest()
        inode = path.stat().st_ino
        repeat_metrics = {}
        if not baseline:
            repeat = writer.publish_changes(path, expected_revision=result['catalog_revision'], upserts=[changed], metrics=repeat_metrics)
            assert repeat['catalog_revision'] == result['catalog_revision']
            assert path.stat().st_ino == inode
        local = (metrics['local_update_seconds']+metrics.get('validation_seconds', 0)
                 + metrics.get('patch_seconds', 0))
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
        passed = (local <= BUDGETS['local_seconds_max']
                  and metrics['normalized_records'] <= BUDGETS['normalized_records_max']
                  and metrics.get('affected_objects', count) <= BUDGETS['affected_objects_max']
                  and elapsed <= BUDGETS['total_seconds_max']
                  and rss <= BUDGETS['process_peak_rss_mib_max'])
        return dict(count=count, mode='baseline' if baseline else 'incremental',
                    budgets=BUDGETS, passed=passed, metrics=metrics,
                    total_wall_seconds=elapsed, local_seconds=local,
                    process_peak_rss_mib=rss, disk_peak_sampled_bytes=disk_peak[0],
                    published_bytes=path.stat().st_size, binary_sha256=binary,
                    catalog_revision=result['catalog_revision'], repeat_metrics=repeat_metrics,
                    build_metrics=build_metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--count', type=int, choices=(100000, 1000000))
    mode.add_argument('--assess', type=Path, help='Recheck a saved combined report without backend dependencies')
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    if args.assess:
        report = json.loads(args.assess.read_text())
        for group in ('baseline', 'incremental'):
            if (len(report[group]) != 2
                    or {run['count'] for run in report[group]} != {100000, 1000000}):
                parser.error(f'{group} must contain exactly one 100k and one 1m run')
        before = {run['count']: run for run in report['baseline']}
        after = {run['count']: run for run in report['incremental']}
        small, large = after[100000], after[1000000]
        checks = {
            'budgets_unchanged': all(run['budgets'] == BUDGETS for run in after.values()),
            'locality_growth': large['local_seconds'] <= (
                small['local_seconds']*BUDGETS['local_growth_ratio_max']
                + BUDGETS['local_growth_allowance_seconds']),
            'same_affected_region': small['metrics']['affected_objects'] == large['metrics']['affected_objects'],
            'same_binary_bytes_and_revision': all(
                run['binary_sha256'] == before[count]['binary_sha256']
                and run['catalog_revision'] == before[count]['catalog_revision']
                for count, run in after.items()),
            'no_op_skips_publication': all(run['repeat_metrics']['no_op']
                and run['repeat_metrics']['copy_seconds'] == 0
                and run['repeat_metrics']['legacy_seconds'] == 0
                for run in after.values()),
            'per_size_budgets': all(
                run['local_seconds'] <= BUDGETS['local_seconds_max']
                and run['metrics']['normalized_records'] <= BUDGETS['normalized_records_max']
                and run['metrics']['affected_objects'] <= BUDGETS['affected_objects_max']
                and run['total_wall_seconds'] <= BUDGETS['total_seconds_max']
                and run['process_peak_rss_mib'] <= BUDGETS['process_peak_rss_mib_max']
                for run in after.values()),
        }
        print(json.dumps(dict(passed=all(checks.values()), checks=checks), sort_keys=True))
        if not all(checks.values()):
            raise SystemExit(1)
        return
    result = measure(args.count, args.baseline)
    print(json.dumps(result, sort_keys=True), flush=True)
    if not args.baseline and not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
