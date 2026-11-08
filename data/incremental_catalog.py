"""Bounded catalog patches, serialized atomic publication and sector reuse.

Compatibility binary sections still require a linear disk pass. This writer
reuses unchanged sector rows; it does not pretend that a full legacy binary
can be patched without rebuilding its parent ordinals and string offsets.
"""
from contextlib import contextmanager
import fcntl
from pathlib import Path

from data.catalog import validate_catalog
from data.coordinates import snapshot_coordinates
from data.runtime_catalog import DiskCatalog
from data.sectors import ResultLimitExceeded, _canonical
from data.streaming_catalog import build_streaming_index


class RevisionConflict(ValueError):
    pass


@contextmanager
def publication_lock(path):
    # Keep the lock inode: unlinking it lets another writer acquire a different
    # inode while a waiter still holds the original lock.
    with Path(str(path)+'.lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream,fcntl.LOCK_UN)


def publish_changes(path, *, expected_revision, upserts=(), deletes=()):
    path = Path(path)
    changes, removed = {}, set()
    size = 0
    for obj in upserts:
        if len(changes)>=4096:
            raise ResultLimitExceeded('patch exceeds 4096 objects')
        local = dict(obj)
        local.pop('parent',None)
        validate_catalog([local]); snapshot_coordinates(obj)
        if obj.get('parent') is not None and (not isinstance(obj['parent'],str) or obj['parent']==obj['id']):
            raise ValueError('invalid parent')
        if obj['id'] in changes:
            raise ValueError('duplicate upsert ID')
        size += len(_canonical(obj).encode())
        if size>8*1024*1024:
            raise ResultLimitExceeded('patch exceeds 8 MiB')
        changes[obj['id']] = obj
    for oid in deletes:
        if not isinstance(oid,str) or not oid or oid in changes:
            raise ValueError('invalid or conflicting delete ID')
        removed.add(oid)
        size += len(oid.encode())
        if len(removed)>4096 or size>8*1024*1024:
            raise ResultLimitExceeded('delete patch exceeds budget')
    with publication_lock(path), DiskCatalog(path).snapshot() as index:
        meta = index.metadata
        if meta['catalog_revision'] != expected_revision:
            raise RevisionConflict('catalog revision changed')
        def rows():
            pending = dict(changes)
            for obj in index.select():
                oid = obj['id']
                if oid not in removed:
                    yield pending.pop(oid,obj)
            for oid in sorted(pending):
                yield pending[oid]
        return build_streaming_index(path,None,objects=rows(),previous_path=path,
                                     cell_size_ly=meta['cell_size_ly'],max_objects=meta['max_objects'],
                                     max_depth=meta['max_depth'],source_signature=meta.get('source_signature'),
                                     parent_revision=expected_revision)
