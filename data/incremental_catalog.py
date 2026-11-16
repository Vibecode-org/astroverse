"""Bounded local SQLite updates, followed by explicit O(N) compatibility work.

The active inode is immutable. A serialized writer copies it privately, updates
only bounded families/base cells, rebuilds global hashes and legacy binaries,
then atomically replaces the publication. Existing readers retain their inode.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from data.coordinates import coordinate_contract
from data.incremental_index import INCREMENTAL_SCHEMA
from data.incremental_region import _region, _update_region
from data.publication import RevisionConflict, publication_lock
from data.runtime_catalog import DiskCatalog
from data.sectors import ResultLimitExceeded, SCHEMA_VERSION, _canonical
from data.streaming_binary import write_catalog_representations
from data.streaming_catalog import validate_record


def _patch(upserts, deletes):
    changes, removed, size = {}, set(), 0
    for obj in upserts:
        if len(changes) >= 4096:
            raise ResultLimitExceeded('patch exceeds 4096 objects')
        obj = validate_record(obj)
        if obj['id'] in changes:
            raise ValueError('duplicate upsert ID')
        payload = _canonical(obj)
        size += len(payload.encode())
        if size > 8 * 1024 * 1024:
            raise ResultLimitExceeded('patch exceeds 8 MiB')
        changes[obj['id']] = obj, payload
    for oid in deletes:
        if not isinstance(oid, str) or not oid or oid in changes:
            raise ValueError('invalid or conflicting delete ID')
        removed.add(oid)
        size += len(oid.encode())
        if len(removed) > 4096 or size > 8 * 1024 * 1024:
            raise ResultLimitExceeded('delete patch exceeds budget')
    return changes, removed


def _publish(path, expected_revision, changes, removed, metrics):
    with publication_lock(path), DiskCatalog(path).snapshot() as index:
        meta = index.metadata
        if meta['catalog_revision'] != expected_revision:
            raise RevisionConflict('catalog revision changed')
        if meta.get('incremental_schema') != INCREMENTAL_SCHEMA:
            raise ValueError('incremental indexes missing or unsupported; rebuild required')
        # Cleanup only this writer's private namespace, under its permanent lock.
        for abandoned in path.parent.glob(f'.{path.name}.patch-*'):
            if abandoned.is_dir() and not abandoned.is_symlink():
                shutil.rmtree(abandoned)
        effective = {}
        for oid, value in changes.items():
            row = index.db.execute('SELECT length(CAST(payload AS BLOB)) FROM objects WHERE id=?', (oid,)).fetchone()
            # Do not materialize an oversized old record merely to establish
            # that a bounded incoming record differs. Region preflight will
            # reject it before any Python payload allocation.
            if row is None or row[0] != len(value[1].encode()):
                effective[oid] = value
            elif index.db.execute('SELECT payload FROM objects WHERE id=?', (oid,)).fetchone()[0] != value[1]:
                effective[oid] = value
        changes = effective
        removed = {oid for oid in removed
                   if index.db.execute('SELECT 1 FROM objects WHERE id=?', (oid,)).fetchone()}
        metrics['normalized_records'] = len(changes)
        metrics['search_rows_written'] = len(changes)
        if not changes and not removed:
            metrics['no_op'] = True
            return meta
        started = time.perf_counter()
        region, final, resolved, cells, payload_bytes = _region(index.db, changes, removed, meta)
        metrics['validation_seconds'] = time.perf_counter() - started
        metrics.update(affected_objects=len(set(region) | set(final)), affected_cells=len(cells),
                       affected_payload_bytes=payload_bytes)
        with tempfile.TemporaryDirectory(dir=path.parent, prefix=f'.{path.name}.patch-',
                                         ignore_cleanup_errors=True) as temporary_dir:
            temporary = Path(temporary_dir) / 'index.sqlite'
            with closing(sqlite3.connect(temporary)) as db:
                db.execute('PRAGMA cache_size=-8192')
                db.execute('PRAGMA temp_store=FILE')
                started = time.perf_counter()
                index.db.backup(db)
                metrics['copy_seconds'] = time.perf_counter() - started
                db.execute('PRAGMA foreign_keys=ON')
                started = time.perf_counter()
                old_sectors, new_sectors = _update_region(db, changes, removed, meta, region, final, resolved, cells)
                metrics['local_update_seconds'] = time.perf_counter() - started
                metrics['affected_sectors'] = len(set(old_sectors) | set(new_sectors))
                started = time.perf_counter()
                digest = hashlib.sha256(_canonical([SCHEMA_VERSION, coordinate_contract(),
                    meta['cell_size_ly'], meta['max_objects'], meta['max_depth']]).encode())
                for payload, in db.execute('SELECT payload FROM objects ORDER BY ordinal'):
                    digest.update(payload.encode())
                    digest.update(b'\n')
                sector_count = db.execute('SELECT count(*) FROM sectors').fetchone()[0]
                metadata = dict(meta, catalog_revision=digest.hexdigest(), parent_revision=expected_revision,
                                object_count=meta['object_count'] + len(final) - len(region),
                                reused_sectors=sector_count - len(new_sectors) + sum(
                                    old_sectors.get(sid) == revision for sid, revision in new_sectors.items()))
                # An administrative patch is not a repeat of the source import.
                # Keep provenance as history but do not claim its old manifest
                # describes the patched semantic catalog.
                if 'import_manifest' in metadata:
                    metadata['previous_import_manifest'] = metadata.pop('import_manifest')
                metrics['global_hash_seconds'] = time.perf_counter() - started
                started = time.perf_counter()
                write_catalog_representations(db)
                metrics['legacy_seconds'] = time.perf_counter() - started
                db.execute('DELETE FROM metadata')
                db.executemany('INSERT INTO metadata VALUES (?,?)',
                               ((key, json.dumps(value)) for key, value in metadata.items()))
                started = time.perf_counter()
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('SQLite integrity failure')
                db.commit()
                metrics['full_validation_seconds'] = time.perf_counter() - started
            started = time.perf_counter()
            with temporary.open('rb') as stream:
                os.fsync(stream.fileno())
            temporary.replace(path)
            metrics['publication_seconds'] = time.perf_counter() - started
        return metadata


def publish_changes(path, *, expected_revision, upserts=(), deletes=(), metrics=None):
    """Publish a <=4096/4096/8MiB patch or reject an oversized affected region.

    Local graph/partition work is capped at 65536 objects, 64MiB payload and
    4096 base cells. Copy, global digest, integrity checks and complete legacy
    output remain O(N), explicitly included in ``metrics['total_seconds']``.
    Old artifacts need an explicit full rebuild to add the incremental indexes.
    """
    started = time.perf_counter()
    metrics = metrics if metrics is not None else {}
    metrics.update({name + '_seconds': 0.0 for name in ('patch', 'validation', 'local_update', 'copy',
                    'global_hash', 'legacy', 'full_validation', 'publication')})
    metrics.update(normalized_records=0, search_rows_written=0, affected_objects=0,
                   affected_cells=0, affected_sectors=0, affected_payload_bytes=0, no_op=False)
    try:
        changes, removed = _patch(upserts, deletes)
        metrics['patch_seconds'] = time.perf_counter() - started
        return _publish(Path(path).resolve(), expected_revision, changes, removed, metrics)
    finally:
        metrics['total_seconds'] = time.perf_counter() - started
