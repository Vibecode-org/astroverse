"""SQLite workload identity and time contract; synthetic never changes real registry."""
import tempfile
import unittest
from pathlib import Path
from tests import s100k_provider as provider

class S100kTest(unittest.TestCase):
    def test_all_identities_and_centers(self):
        ids=set()
        for sector in range(100):
            frame=provider.payload('2020-01-01T00:00:00Z',f's100k:{sector}')
            self.assertTrue(frame['synthetic'])
            self.assertEqual(len(frame['objects']),1000)
            for row in frame['objects']:
                n=int(row['id'].split('-')[1]);k=50000 if n==50001 else n
                self.assertEqual(row['position'],[(k%400-199.5)*4000,0,(k//400-124.5)*4000])
                self.assertNotIn(row['id'],ids);ids.add(row['id'])
        self.assertEqual(len(ids),100000)
    def test_stationary_requested_time_and_sqlite_rebuild(self):
        a=provider.payload('2020-01-01T00:00:00Z','s100k:0');b=provider.payload('2021-01-01T00:00:00Z','s100k:0')
        self.assertEqual(a['objects'],b['objects']);self.assertNotEqual(a['jd_tdb'],b['jd_tdb'])
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'b.sqlite';provider.build(path);provider.build(path)
            import sqlite3
            with sqlite3.connect(path) as db:self.assertEqual(db.execute('select count(*) from bodies').fetchone()[0],100000)
