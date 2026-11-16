"""Atomic bounded patches preserve pinned readers and independent sector ETags."""
import json
from pathlib import Path
import tempfile
import sqlite3
from unittest.mock import patch
import unittest

from data.incremental_catalog import publish_changes, RevisionConflict
from data.runtime_catalog import DiskCatalog
from data.sectors import SectorIndex, ResultLimitExceeded
from data.catalog import encode_binary_catalog_v2
from data.streaming_catalog import build_streaming_index
from tests.test_sectors import star


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'index.sqlite'
        self.source=Path(self.tmp.name)/'source.json'
        self.items=[star('a',1),star('b',100),dict(id='c',name='c',kind='exoplanet',scale='local',parent='a')]
        self.source.write_text(json.dumps(self.items))
        self.meta=build_streaming_index(self.path,self.source,max_objects=1)

    def test_changes_move_whole_families_preserve_readers_and_reuse_unrelated_sectors(self):
        old=SectorIndex(self.path)
        b_sector=old.locate('b')
        a_sector=old.locate('a')
        previous={row['id']:row['revision'] for row in old.sectors()}
        with DiskCatalog(self.path).snapshot() as pinned:
            changed=star('a',50)
            meta=publish_changes(self.path,expected_revision=self.meta['catalog_revision'],upserts=[changed,star('new',300)])
            self.assertEqual(pinned.object('a')['distance_ly'],1)
            self.assertIsNone(pinned.object('new'))
        fresh=SectorIndex(self.path)
        self.assertNotEqual(fresh.locate('a'),old.locate('b'))
        self.assertEqual(fresh.locate('a'),fresh.locate('c'))
        self.assertNotEqual(fresh.locate('a'),a_sector)
        self.assertGreaterEqual(meta['reused_sectors'],1)
        after={row['id']:row['revision'] for row in fresh.sectors()}
        self.assertEqual(previous[b_sector],after[b_sector])
        with DiskCatalog(self.path).snapshot() as index:
            self.assertEqual([o['id'] for o in index.select()],['a','b','c','new'])
            expected=[changed,self.items[1],self.items[2],star('new',300)]
            self.assertEqual(b''.join(index.binary('v2')),encode_binary_catalog_v2(expected))
        before=self.path.read_bytes()
        with self.assertRaises(RevisionConflict):
            publish_changes(self.path,expected_revision=self.meta['catalog_revision'])
        self.assertEqual(before,self.path.read_bytes())
        removed=publish_changes(self.path,expected_revision=meta['catalog_revision'],deletes=['a','c'])
        self.assertEqual(removed['object_count'],2)
        self.assertIsNone(SectorIndex(self.path).locate('a'))

    def test_invalid_or_oversize_patches_leave_artifact_intact(self):
        before=self.path.read_bytes()
        kwargs=[{'upserts':[star('d',1),star('d',2)]}, {'deletes':['a']},
                {'deletes':[None]}, {'deletes':['a'],'upserts':[star('a',1)]},
                {'upserts':[star('a',1,parent='a')]},{'upserts':[star('a',1,parent=123)]},
                {'upserts':[star('d',1,description='x'*(8*1024*1024))]},
                {'upserts':(star(str(i),1) for i in range(4097))},
                {'deletes':(str(i) for i in range(4097))}]
        for options in kwargs:
            with self.subTest(options=list(options)),self.assertRaises(ValueError):
                publish_changes(self.path,expected_revision=self.meta['catalog_revision'],**options)
            self.assertEqual(before,self.path.read_bytes())

    def test_consumer_errors_are_not_mislabeled_as_storage_failures(self):
        with self.assertRaises(ResultLimitExceeded):
            with DiskCatalog(self.path).snapshot() as index:
                raise ResultLimitExceeded('caller limit')
        with self.assertRaises(ValueError):
            with DiskCatalog(self.path).snapshot():
                raise ValueError('invalid caller input')


class LocalWriterTests(unittest.TestCase):
    setUp = IncrementalTests.setUp
    def test_noop_repeat_missing_deletes_preserve_inode_and_revision(self):
        before = self.path.read_bytes()
        inode = self.path.stat().st_ino
        metrics = {}
        result = publish_changes(self.path, expected_revision=self.meta['catalog_revision'],
                                 upserts=[self.items[0]], deletes=['missing'], metrics=metrics)
        self.assertEqual(result, self.meta)
        self.assertEqual(self.path.stat().st_ino, inode)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(metrics['no_op'])
        self.assertEqual(metrics['affected_objects'], 0)
        self.assertEqual(metrics['copy_seconds'], 0)
        with self.assertRaises(RevisionConflict):
            publish_changes(self.path, expected_revision='stale', upserts=[self.items[0]])

    def test_only_patch_is_normalized_and_unchanged_search_payload_are_not_written(self):
        # Put independent families in one cell to exercise sibling repartition.
        items = [star('a', 1), star('b', 2)]
        self.meta = build_streaming_index(self.path, None, objects=items, max_objects=1)
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TRIGGER prohibit_unchanged_search
                BEFORE UPDATE OF payload,search_blob ON objects WHEN OLD.id='b'
                BEGIN SELECT RAISE(ABORT, 'unchanged payload/search rewritten'); END""")
        from data.streaming_catalog import validate_record
        metrics = {}
        with patch('data.incremental_catalog.validate_record', wraps=validate_record) as normalize:
            result = publish_changes(self.path, expected_revision=self.meta['catalog_revision'],
                                     upserts=[star('a', 20)], metrics=metrics)
        self.assertEqual(normalize.call_count, 1)
        self.assertEqual(metrics['normalized_records'], 1)
        self.assertEqual(metrics['search_rows_written'], 1)
        self.assertEqual(metrics['affected_objects'], 2)
        self.assertEqual(metrics['affected_cells'], 1)
        self.assertGreater(metrics['affected_payload_bytes'], 0)
        self.assertEqual(result['object_count'], 2)
        for stage in ('patch', 'validation', 'local_update', 'copy', 'global_hash',
                      'legacy', 'publication', 'full_validation'):
            self.assertGreaterEqual(metrics[stage + '_seconds'], 0)
        self.assertGreater(metrics['total_seconds'], metrics['local_update_seconds'])

    def test_affected_bounds_reject_before_publication_including_old_new_union(self):
        before, inode = self.path.read_bytes(), self.path.stat().st_ino
        cases = [('MAX_AFFECTED_OBJECTS', 1, dict(upserts=[star('a', 2)])),
                 ('MAX_AFFECTED_OBJECTS', 2, dict(upserts=[star('d', 1)], deletes=['c'])),
                 ('MAX_AFFECTED_BYTES', 1, dict(upserts=[star('a', 2)])),
                 ('MAX_AFFECTED_CELLS', 1, dict(upserts=[star('a', 50)]))]
        for constant, limit, options in cases:
            with self.subTest(constant=constant, options=options):
                with patch('data.incremental_region.' + constant, limit), self.assertRaises(ResultLimitExceeded):
                    publish_changes(self.path, expected_revision=self.meta['catalog_revision'], **options)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertEqual(self.path.stat().st_ino, inode)

    def test_old_schema2_is_readable_but_patch_requires_explicit_rebuild(self):
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM metadata WHERE key='incremental_schema'")
        self.assertEqual(len(DiskCatalog(self.path)), 3)
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'rebuild required'):
            publish_changes(self.path, expected_revision=self.meta['catalog_revision'], upserts=[star('a', 2)])
        self.assertEqual(self.path.read_bytes(), before)

    def test_admin_patch_moves_import_manifest_to_history(self):
        manifest = {'source': 'test', 'semantic_revision': self.meta['catalog_revision']}
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO metadata VALUES ('import_manifest',?)", (json.dumps(manifest),))
        result = publish_changes(self.path, expected_revision=self.meta['catalog_revision'], upserts=[star('a', 2)])
        self.assertNotIn('import_manifest', result)
        self.assertEqual(result['previous_import_manifest'], manifest)


    def test_all_new_region_reports_payload_bytes(self):
        metrics = {}
        result = publish_changes(self.path, expected_revision=self.meta['catalog_revision'],
                                 upserts=[star('new', 500)], metrics=metrics)
        self.assertEqual(metrics['affected_objects'], 1)
        self.assertGreater(metrics['affected_payload_bytes'], 0)
        self.assertEqual(result['object_count'], 4)
