"""Streamed artifacts must preserve the reference index and legacy wire bytes."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.catalog import load_catalog
from data.runtime_catalog import DiskCatalog
from data.sectors import build_sector_index, SectorIndex
from data.streaming_catalog import build_streaming_index, iter_catalog
from tests.test_sectors import star


class StreamingCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'source.json'
        self.target = self.root/'stream.sqlite'

    def compare(self, items, **options):
        self.source.write_text(json.dumps(items,ensure_ascii=False))
        reference = self.root/'reference.sqlite'
        build_sector_index(reference,items,**options)
        build_streaming_index(self.target,self.source,**options)
        before,after = SectorIndex(reference),SectorIndex(self.target)
        self.assertEqual(before.sectors(),after.sectors())
        self.assertEqual(before.metadata['catalog_revision'],after.metadata['catalog_revision'])
        with DiskCatalog(reference).snapshot() as a, DiskCatalog(self.target).snapshot() as b:
            self.assertEqual(list(a.select()),list(b.select()))
            for fmt in ['v1','v2']:
                self.assertEqual(b''.join(a.binary(fmt)),b''.join(b.binary(fmt)))
        for sector in before.sectors():
            self.assertEqual(before.objects(sector['id']),after.objects(sector['id']))
        with sqlite3.connect(self.target) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('input','families','strings','cells')").fetchone())

    def test_wire_bytes_revisions_order_and_adaptive_partitioning(self):
        items=[dict(id='moon',name='Луна',kind='moon',scale='local',parent='planet'),
               dict(id='planet',name='Earth',latin='Earth',kind='planet',scale='local',parent='host',radius=2),
               star('host',1,name_alias='unused'),star('b',3,latin='Earth'),star('c',20),star('d',30),
               star('negative',10,ra=12),star('unknown',None),
               dict(id='sun',name='Sun',kind='star',scale='solar',radius=1),
               dict(id='black',name='黑洞',kind='black_hole',scale='galaxy',galactic_l=0,galactic_b=0,distance_ly=10,has_jet=True),
               dict(id='cluster',name='黑洞',kind='cluster',scale='galaxy')]
        self.compare(items,max_objects=1,max_depth=4)
        self.compare([star('a',1),star('b',1)],max_objects=1,max_depth=2)
        self.compare([])

    def test_full_seed_matches_reference_without_loss(self):
        self.compare(load_catalog(Path(__file__).parents[1]/'data/catalog_seed.json'))

    def test_invalid_data_never_replaces_previous_publication(self):
        self.compare([star('a',1)])
        before = self.target.read_bytes()
        for items in [[star('a',1),star('a',2)], [star('a',1,parent='missing')],
                      [star('a',1,parent='a')], [star('a',1,parent=3)],
                      [star('a',1,parent='b'),star('b',2,parent='a')],
                      [star('a',1),dict(id='b',name='b',scale='solar',kind='moon',parent='a')],
                      [None], [star('a',float('nan'))], [star('a',1,galactic_b=1000,galactic_l=0)]]:
            self.source.write_text(json.dumps(items))
            # Galactic fields are ignored in favor of a complete RA/Dec pair.
            if isinstance(items[0],dict) and 'galactic_b' in items[0]:
                continue
            with self.subTest(items=items),self.assertRaises(ValueError):
                build_streaming_index(self.target,self.source)
            self.assertEqual(self.target.read_bytes(),before)
        for text in ['{}','null','[','[] []','[true]','[{}]']:
            self.source.write_text(text)
            with self.subTest(text=text),self.assertRaises(ValueError):
                build_streaming_index(self.target,self.source)
            self.assertEqual(self.target.read_bytes(),before)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),['reference.sqlite','source.json','stream.sqlite'])

    def test_configuration_physical_limits_and_ra_normalization(self):
        self.source.write_text(json.dumps([star('a',1,ra=24)]))
        self.assertEqual(next(iter_catalog(self.source))['ra'],0)
        for opts in [{'cell_size_ly':0},{'cell_size_ly':True},{'max_depth':33},{'max_objects':0},
                     {'cell_size_ly':1e-323}, {'cell_size_ly':1e-20}]:
            with self.subTest(opts=opts),self.assertRaises(ValueError):
                build_streaming_index(self.target,self.source,**opts)
        with self.assertRaises(ValueError):
            build_streaming_index(self.source,self.source)
        self.source.write_text(json.dumps([star('extreme',3e38)]))
        with self.assertRaises(ValueError):
            build_streaming_index(self.target,self.source,cell_size_ly=3e38)
