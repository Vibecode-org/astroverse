"""Publication boundaries: HTTP validators, open readers, races and crashes."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import quote

from backend.prepare_runtime import ensure_runtime, signature
from data.catalog import encode_binary_catalog, encode_binary_catalog_v2
from data.incremental_catalog import publish_changes
from data.runtime_catalog import DiskCatalog
from data.sectors import SectorIndex
from data.streaming_catalog import build_streaming_index
from tests.import_http import api
from tests.test_sectors import star


REPO = Path(__file__).resolve().parents[1]


class IncrementalPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / 'published.sqlite'
        self.source = self.root / 'source.json'
        self.items = [star('a', 1), star('b', 100),
                      dict(id='child', name='child', kind='exoplanet',
                           scale='local', parent='a')]
        self.source.write_text(json.dumps(self.items))
        self.meta = build_streaming_index(
            self.path, self.source, max_objects=1,
            source_signature=signature(self.source))

    def publish(self, **options):
        return publish_changes(self.path,
                               expected_revision=self.meta['catalog_revision'],
                               **options)

    def process(self, code, *args):
        child = subprocess.Popen([sys.executable, '-c', code, *map(str, args)],
                                 cwd=REPO, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_process, child)
        return child

    @staticmethod
    def stop_process(child):
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)

    def wait_file(self, file, child):
        deadline = time.monotonic() + 20
        while not file.exists():
            if child.poll() is not None:
                output, errors = child.communicate()
                self.fail(f'writer exited before publication boundary: {output} {errors}')
            if time.monotonic() >= deadline:
                self.fail('writer did not reach publication boundary')
            time.sleep(.01)

    def test_http_unchanged_sector_etag_new_snapshot_and_stale_before_304(self):
        index = SectorIndex(self.path)
        unchanged = index.locate('b')
        changed = index.locate('a')
        route = '/api/spatial/v1/sectors/' + quote(unchanged, safe='/:') + '?limit=1'
        changed_route = '/api/spatial/v1/sectors/' + quote(changed, safe='/:') + '?limit=1'
        with api(self.path) as get:
            status, before, headers = get(route)
            self.assertEqual(status, 200)
            old_snapshot, old_etag = headers['X-Catalog-Snapshot'], headers['ETag']
            self.assertEqual(old_snapshot, self.meta['catalog_revision'])
            changed_etag = get(changed_route)[2]['ETag']
            # Change a payload while retaining the affected leaf ID.
            result = self.publish(upserts=[dict(self.items[0], description='updated')])
            self.assertNotEqual(result['catalog_revision'], old_snapshot)
            status, payload, current = get(route, {'If-None-Match': 'W/' + old_etag})
            self.assertEqual(status, 304)
            self.assertIsNone(payload)
            self.assertEqual(current['ETag'], old_etag)
            self.assertEqual(current['X-Catalog-Snapshot'], result['catalog_revision'])
            self.assertEqual(get(route)[1], before)
            status, payload, current = get(route + '&snapshot=' + old_snapshot,
                                           {'If-None-Match': old_etag})
            self.assertEqual(status, 409)
            self.assertEqual(payload['detail']['code'], 'snapshot_changed')
            self.assertEqual(payload['detail']['snapshot'], result['catalog_revision'])
            status, _, changed_headers = get(changed_route,
                                             {'If-None-Match': changed_etag})
            self.assertEqual(status, 200)
            self.assertNotEqual(changed_headers['ETag'], changed_etag)
            self.assertEqual(changed_headers['X-Catalog-Snapshot'], result['catalog_revision'])

    def test_open_blob_and_snapshot_remain_on_old_inode_after_publication(self):
        # A large unique string makes v2 span multiple blob.read chunks.
        self.items[0]['name'] = 'a' * 80000
        self.source.write_text(json.dumps(self.items))
        self.meta = build_streaming_index(self.path, self.source, max_objects=1)
        expected_v1 = encode_binary_catalog(self.items)
        expected_v2 = encode_binary_catalog_v2(self.items)
        old_inode = self.path.stat().st_ino
        with DiskCatalog(self.path).snapshot() as pinned:
            stream = pinned.binary('v2')
            prefix = next(stream)
            self.assertEqual(len(prefix), 65536)
            result = self.publish(upserts=[dict(self.items[0], name='new name')])
            self.assertNotEqual(self.path.stat().st_ino, old_inode)
            self.assertEqual(pinned.metadata['catalog_revision'], self.meta['catalog_revision'])
            self.assertEqual(pinned.object('a')['name'], self.items[0]['name'])
            self.assertEqual(prefix + b''.join(stream), expected_v2)
            self.assertEqual(b''.join(pinned.binary('v1')), expected_v1)
        with DiskCatalog(self.path).snapshot() as current:
            self.assertEqual(current.metadata['catalog_revision'], result['catalog_revision'])
            self.assertEqual(current.object('a')['name'], 'new name')
            self.assertNotEqual(b''.join(current.binary('v2')), expected_v2)

    def test_two_process_writers_serialize_expected_revision(self):
        gate = self.root / 'start'
        code = '''
import json, sys, time
from pathlib import Path
from data.incremental_catalog import publish_changes, RevisionConflict
path, revision, gate, oid = sys.argv[1:]
while not Path(gate).exists():
    time.sleep(.01)
try:
    result = publish_changes(path, expected_revision=revision,
        upserts=[dict(id=oid, name=oid, kind='star', scale='local',
                      ra=0, dec=0, distance_ly=500)])
    print(json.dumps(dict(status='published', revision=result['catalog_revision'], id=oid)))
except RevisionConflict:
    print(json.dumps(dict(status='conflict', id=oid)))
'''
        children = [self.process(code, self.path, self.meta['catalog_revision'], gate, oid)
                    for oid in ('writer-one', 'writer-two')]
        gate.touch()
        outcomes = []
        for child in children:
            output, errors = child.communicate(timeout=30)
            self.assertEqual(child.returncode, 0, errors)
            outcomes.append(json.loads(output))
        self.assertEqual(sorted(row['status'] for row in outcomes), ['conflict', 'published'])
        winner = next(row for row in outcomes if row['status'] == 'published')
        loser = next(row for row in outcomes if row['status'] == 'conflict')
        with DiskCatalog(self.path).snapshot() as current:
            self.assertEqual(current.metadata['catalog_revision'], winner['revision'])
            self.assertIsNotNone(current.object(winner['id']))
            self.assertIsNone(current.object(loser['id']))
            self.assertEqual(current.metadata['object_count'], len(self.items) + 1)

    def test_candidate_is_fsynced_before_atomic_replace(self):
        original_fsync, original_replace = os.fsync, Path.replace
        synced, published = set(), []

        def fsync(descriptor):
            synced.add(os.fstat(descriptor).st_ino)
            return original_fsync(descriptor)

        def replace(source, target):
            if Path(target) == self.path:
                self.assertIn(source.stat().st_ino, synced)
                published.append(source)
            return original_replace(source, target)

        with patch('os.fsync', fsync), patch.object(Path, 'replace', replace):
            self.publish(upserts=[dict(self.items[0], description='updated')])
        self.assertEqual(len(published), 1)

    def test_failed_atomic_replace_leaves_active_publication_unchanged(self):
        before, inode = self.path.read_bytes(), self.path.stat().st_ino
        original_replace = Path.replace

        def fail_replace(source, target):
            if Path(target) == self.path:
                raise OSError('injected pre-publication failure')
            return original_replace(source, target)

        with patch.object(Path, 'replace', fail_replace), self.assertRaisesRegex(
                OSError, 'injected pre-publication failure'):
            self.publish(upserts=[dict(self.items[0], description='updated')])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(SectorIndex(self.path).metadata['catalog_revision'],
                         self.meta['catalog_revision'])
        self.assertFalse(list(self.root.glob('.published.sqlite.*')))

    def test_failed_candidate_fsync_leaves_active_publication_unchanged(self):
        before, inode = self.path.read_bytes(), self.path.stat().st_ino
        with patch('os.fsync', side_effect=OSError('injected fsync failure')):
            with self.assertRaisesRegex(OSError, 'injected fsync failure'):
                self.publish(upserts=[dict(self.items[0], description='updated')])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertFalse(list(self.root.glob('.published.sqlite.*')))

    def test_cleanup_error_after_commit_returns_success_and_next_writer_cleans(self):
        original_rmdir = os.rmdir

        def deny_stage_removal(path, *args, **options):
            if Path(path).name.startswith('.published.sqlite.patch-'):
                raise PermissionError('injected post-commit cleanup failure')
            return original_rmdir(path, *args, **options)

        with patch('os.rmdir', deny_stage_removal):
            result = self.publish(upserts=[star('survivor', 600)])
        self.assertEqual(SectorIndex(self.path).metadata['catalog_revision'], result['catalog_revision'])
        self.assertTrue(list(self.root.glob('.published.sqlite.patch-*')))
        inode = self.path.stat().st_ino
        # A repeat only cleans the abandoned staging directory, retaining the
        # successful publication and its revision/inode.
        repeated = publish_changes(self.path, expected_revision=result['catalog_revision'])
        self.assertEqual(repeated['catalog_revision'], result['catalog_revision'])
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertFalse(list(self.root.glob('.published.sqlite.patch-*')))

    def test_killed_writer_preserves_active_and_next_writer_cleans_private_stage(self):
        marker = self.root / 'ready'
        code = '''
import sys, time
from pathlib import Path
from data.incremental_catalog import publish_changes
path, revision, marker = sys.argv[1:]
original_replace = Path.replace
def stop_before_replace(source, target):
    if Path(target) == Path(path):
        Path(marker).write_text(str(source))
        while True:
            time.sleep(.1)
    return original_replace(source, target)
Path.replace = stop_before_replace
publish_changes(path, expected_revision=revision,
    upserts=[dict(id='killed', name='killed', kind='star', scale='local',
                  ra=0, dec=0, distance_ly=500)])
'''
        before, inode = self.path.read_bytes(), self.path.stat().st_ino
        child = self.process(code, self.path, self.meta['catalog_revision'], marker)
        self.wait_file(marker, child)
        stage = Path(marker.read_text()).parent
        self.assertNotEqual(stage, self.root)
        self.assertTrue(stage.exists())
        child.kill()
        child.communicate(timeout=10)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(SectorIndex(self.path).metadata['catalog_revision'],
                         self.meta['catalog_revision'])
        result = self.publish(upserts=[star('survivor', 600)])
        self.assertFalse(stage.exists())
        with DiskCatalog(self.path).snapshot() as current:
            self.assertEqual(current.metadata['catalog_revision'], result['catalog_revision'])
            self.assertIsNone(current.object('killed'))
            self.assertIsNotNone(current.object('survivor'))

    def test_ensure_runtime_restart_keeps_patch_without_rebuilding_json(self):
        result = self.publish(upserts=[star('survivor', 600)])
        before, inode = self.path.read_bytes(), self.path.stat().st_ino
        with patch.dict(os.environ, {'ASTROVERSE_SECTOR_PATH': str(self.path),
                                     'ASTROVERSE_CATALOG_MODE': 'offline'}), patch(
                'backend.prepare_runtime.subprocess.run',
                side_effect=AssertionError('restart tried to rebuild source JSON')):
            self.assertEqual(ensure_runtime(self.source), self.path)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(SectorIndex(self.path).metadata['catalog_revision'], result['catalog_revision'])
        # A real new API process opens exactly the patched publication.
        with api(self.path) as get:
            self.assertEqual(get('/api/health')[1]['objects'], len(self.items) + 1)
            self.assertEqual(get('/api/objects/survivor')[1]['id'], 'survivor')

    def test_killed_after_atomic_replace_keeps_committed_revision_on_restart(self):
        marker = self.root / 'committed'
        code = '''
import sys, time
from pathlib import Path
from data.incremental_catalog import publish_changes
path, revision, marker = sys.argv[1:]
original_replace = Path.replace
def stop_after_replace(source, target):
    result = original_replace(source, target)
    if Path(target) == Path(path):
        Path(marker).write_text(str(source.parent))
        while True:
            time.sleep(.1)
    return result
Path.replace = stop_after_replace
publish_changes(path, expected_revision=revision,
    upserts=[dict(id='committed', name='committed', kind='star', scale='local',
                  ra=0, dec=0, distance_ly=500)])
'''
        old_inode = self.path.stat().st_ino
        child = self.process(code, self.path, self.meta['catalog_revision'], marker)
        self.wait_file(marker, child)
        stage = Path(marker.read_text())
        child.kill()
        child.communicate(timeout=10)
        committed = SectorIndex(self.path).metadata['catalog_revision']
        self.assertNotEqual(committed, self.meta['catalog_revision'])
        self.assertNotEqual(self.path.stat().st_ino, old_inode)
        with patch.dict(os.environ, {'ASTROVERSE_SECTOR_PATH': str(self.path),
                                     'ASTROVERSE_CATALOG_MODE': 'offline'}), patch(
                'backend.prepare_runtime.subprocess.run',
                side_effect=AssertionError('restart replaced committed patch')):
            self.assertEqual(ensure_runtime(self.source), self.path)
        with api(self.path) as get:
            self.assertEqual(get('/api/objects/committed')[1]['id'], 'committed')
            headers = get('/api/spatial/v1/sectors/' +
                          quote(SectorIndex(self.path).locate('committed'), safe='/:'))[2]
            self.assertEqual(headers['X-Catalog-Snapshot'], committed)
        publish_changes(self.path, expected_revision=committed)
        self.assertFalse(stage.exists())
        self.assertEqual(SectorIndex(self.path).metadata['catalog_revision'], committed)


if __name__ == '__main__':
    unittest.main()
