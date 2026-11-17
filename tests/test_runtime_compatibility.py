"""Production API compatibility with only a SQLite artifact available."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

from data.streaming_catalog import build_streaming_index


ROOT = Path(__file__).resolve().parents[1]


class RuntimeCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="astroverse-runtime-api-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.path = Path(cls.temporary.name) / "catalog.sqlite"
        # Deliberately keep catalog order distinct from ID order. The child
        # precedes its parent, as supported by the existing catalog contract.
        cls.items = [
            dict(id="earth", name="Земля", latin="Earth", kind="planet", scale="solar",
                 parent="sun", description="Наш дом", facts=["Кириллица"], jpl_command="Earth"),
            dict(id="sun", name="Солнце", latin="Sol", kind="star", scale="solar", jpl_command="Sun"),
            dict(id="unknown", name="Unknown", kind="star", scale="local"),
            dict(id="alpha", name="Alpha", kind="star", scale="local"),
        ]
        build_streaming_index(cls.path, None, objects=iter(cls.items))

    def run_api(self, checks):
        prefix = """
import os
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import data.catalog
import data.build_catalog
import data.streaming_catalog

def forbidden(*args, **kwargs):
    raise AssertionError('Production API tried to prepare JSON or materialize a catalog')

data.catalog.load_catalog = forbidden
data.build_catalog.build_enriched_catalog = forbidden
data.streaming_catalog.build_streaming_index = forbidden
with patch('urllib.request.urlopen', side_effect=forbidden):
    from backend import app as api
from data.runtime_catalog import DiskCatalog
assert isinstance(api.CATALOG, DiskCatalog)
assert not Path(os.environ['ASTROVERSE_CATALOG_PATH']).exists()
DiskCatalog.__iter__ = forbidden
api.build_catalog_index = forbidden
"""
        script = textwrap.dedent(prefix) + "\nitems = " + repr(self.items) + "\n" + textwrap.dedent(checks)
        env = {**os.environ, "ASTROVERSE_CATALOG_MODE": "offline",
               "ASTROVERSE_SECTOR_PATH": str(self.path),
               "ASTROVERSE_CATALOG_PATH": str(self.path.parent / "absent.json"),
               "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_health_full_streams_and_legacy_binary_order_without_json(self):
        self.run_api("""
            from data.catalog import encode_binary_catalog, encode_binary_catalog_v2
            with TestClient(api.app) as client:
                assert client.get('/api/health').json() == {'status': 'ok', 'objects': len(items)}
                assert client.get('/api/objects').json() == items
                for route, headers, encoder, version in (
                    ('/api/objects', {'Accept': 'application/octet-stream'}, encode_binary_catalog, 'v1'),
                    ('/api/objects?format=v2', {}, encode_binary_catalog_v2, 'v2'),
                ):
                    response = client.get(route, headers=headers)
                    assert response.status_code == 200
                    assert response.content == encoder(items)
                    assert response.headers['x-catalog-format'] == version
                    assert response.headers['x-object-count'] == str(len(items))
                    assert int(response.headers['content-length']) == len(response.content)
                assert api._CATALOG_INDEX['catalog'] is None
                try:
                    api.catalog_index()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('DiskCatalog accepted by in-memory catalog_index')
        """)

    def test_search_detail_filters_and_legacy_validators_without_list_index(self):
        self.run_api("""
            with TestClient(api.app) as client:
                assert client.get('/api/search', params={'q': 'КИРИЛЛИЦА'}).json()[0]['id'] == 'earth'
                assert client.get('/api/search', params={'q': 'star'}).json() == []
                assert client.get('/api/objects/earth').json() == items[0]
                assert client.get('/api/objects/absent').status_code == 404
                assert client.get('/api/objects?scale=solar').json() == items[:2]
                route = '/api/objects?q=%D0%BA%D0%B8%D1%80%D0%B8%D0%BB%D0%BB%D0%B8%D1%86%D0%B0'
                first = client.get(route)
                assert first.json() == items[:1]
                assert first.headers['vary'] == 'Accept'
                etag = first.headers['etag']
                etag.encode('latin-1')
                for validator in (etag, 'W/' + etag, '\"unrelated\", W/' + etag, '*'):
                    response = client.get(route, headers={'If-None-Match': validator})
                    assert response.status_code == 304 and response.content == b''
                assert client.get(route, headers={'If-None-Match': '\"unrelated\"'}).status_code == 200
                assert api._CATALOG_INDEX['catalog'] is None
        """)

    def test_filtered_conditional_cannot_bypass_object_or_byte_budget(self):
        self.run_api("""
            with TestClient(api.app) as client:
                for version in ('json', 'v1', 'v2'):
                    route = '/api/objects?kind=star&format=' + version
                    accept = {'Accept': 'application/octet-stream'} if version == 'v1' else {}
                    valid = client.get(route, headers=accept)
                    assert valid.status_code == 200
                    for budget, value in (('LEGACY_FILTER_MAX_OBJECTS', 1),
                                          ('LEGACY_FILTER_MAX_BYTES', 1)):
                        # New cache instances avoid a payload validated under old limits.
                        from backend.byte_cache import ByteLRU
                        with patch.object(api, budget, value), patch.object(api, 'SERIALIZED_CACHE', ByteLRU(8192)):
                            for condition in ('*', valid.headers['etag'], 'W/' + valid.headers['etag']):
                                response = client.get(route, headers={**accept, 'If-None-Match': condition})
                                assert response.status_code == 413, (budget, version, response.status_code)
        """)

    def test_snapshot_pages_keep_id_order_null_physics_and_time_rejection(self):
        self.run_api("""
            with TestClient(api.app) as client:
                route = '/api/spatial/v1/sectors/solar:system?limit=1'
                first = client.get(route)
                assert first.status_code == 200
                page = first.json()
                assert page['objects'][0]['object']['id'] == 'earth'
                assert page['next_after'] == 'earth'
                assert page['objects'][0]['coordinates']['simulation_position'] is None
                second = client.get(route + '&after=earth').json()
                assert second['objects'][0]['object']['id'] == 'sun'
                assert second['next_after'] is None
                assert client.get(route + '&at=now').status_code == 422
                assert client.get(route + '&snapshot=obsolete', headers={'If-None-Match': first.headers['etag']}).status_code == 409
                assert client.get(route, headers={'If-None-Match': 'W/' + first.headers['etag']}).status_code == 304
                unknown = client.get('/api/spatial/v1/objects/unknown/sector').json()
                assert unknown['coordinates']['position'] is None
        """)

    def test_legacy_live_targets_are_selected_from_sqlite_without_full_iteration(self):
        self.run_api("""
            with TestClient(api.app) as client:
                with patch.object(api, 'fetch_jpl_vector', return_value={'x': 1, 'y': 2, 'z': 3}) as fetch:
                    response = client.get('/api/live-ephemeris')
                assert response.status_code == 200
                assert list(response.json()['positions']) == ['earth', 'sun']
                assert [call.args[0] for call in fetch.call_args_list] == ['Earth', 'Sun']
        """)
