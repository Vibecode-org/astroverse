"""Import then consume/switch revisions through real production HTTP."""
from pathlib import Path
import tempfile
import unittest

from data.import_sbdb import import_sbdb
from data.streaming_catalog import build_streaming_index
from tests.sbdb_fixture import serve
from tests.import_http import api, checks


class ImportHTTPTests(unittest.TestCase):
    def test_published_sqlite_without_json_and_live_revision_switch(self):
        with tempfile.TemporaryDirectory() as tmp, serve() as (url, _):
            path = Path(tmp)/'catalog.sqlite'
            initial = build_streaming_index(path, None, objects=iter([dict(id='sun', name='Sun', kind='star', scale='solar')]))
            result = import_sbdb(path, expected_revision=initial['catalog_revision'], url=url, limit=3)
            with api(path) as get:
                checks(get, 4)
                route = '/api/spatial/v1/sectors/solar:system?limit=2'
                _, page, headers = get(route)
                with serve(1, change=0) as (changed_url, _):
                    result = import_sbdb(path, expected_revision=result['metadata']['catalog_revision'], url=changed_url, limit=1)
                self.assertEqual(get(route+'&snapshot='+headers['X-Catalog-Snapshot'], {'If-None-Match': headers['ETag']})[0], 409)
                self.assertEqual(get('/api/objects/sbdb:a:0')[1]['radius_km'], 1)
                self.assertNotEqual(get(route)[2]['X-Catalog-Snapshot'], headers['X-Catalog-Snapshot'])
