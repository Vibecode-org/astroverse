"""Atomic bounded patches preserve pinned readers and independent sector ETags."""
import json
from pathlib import Path
import tempfile
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
