"""The synthetic HTTP fixture is opt-in and exercises the positions wire shape."""
import copy
import unittest
from fastapi.testclient import TestClient
from tests import sector_provider as fixture

AT = '2026-11-06T00:00:00.123Z'


class SyntheticHTTPProviderTests(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy(fixture.state)
        fixture.state.update(delay=0, fail='', hang='', conflict=0, mixed='')
        self.client = TestClient(fixture.app)

    def tearDown(self):
        fixture.state.update(self.saved)
        self.client.close()

    def test_isolated_composition_and_manifest(self):
        self.assertTrue(self.client.get('/api/health').json()['synthetic'])
        rows = self.client.get('/api/sources/v1/objects').json()['objects']
        self.assertEqual(len(rows),128)
        self.assertTrue(all(row['id'].startswith('synthetic-') for row in rows))
        query = dict(at=AT,anchor='synthetic-000',dx=0,dy=0,dz=0,radius=1e9)
        manifest = self.client.get('/api/positions/v1/nearby',params=query).json()
        self.assertEqual(len(manifest['sectors']),32)
        self.assertEqual(manifest['objects'],[])
        query['dx'] = 1e12; query['radius'] = 1
        self.assertEqual(self.client.get('/api/positions/v1/nearby',params=query).json()['sectors'],[])

    def test_sector_time_identity_and_unknown(self):
        response = self.client.get('/api/positions/v1/sectors/synthetic:2',params={'at':AT,'revision':fixture.current_revision()})
        self.assertEqual(response.status_code,200)
        self.assertLess(len(response.content),256*1024)
        body = response.json(); self.assertEqual(len(body['objects']),64)
        self.assertEqual(body['objects'][-1]['position'],None)
        self.assertEqual(body['hierarchy']['jd_tdb'],body['jd_tdb'])
        self.assertEqual(body['hierarchy']['evaluated_at'],body['evaluated_at'])
        self.assertTrue(body['evaluated_at'].startswith('2026-11-06T00:00:00.123'))
        self.assertEqual(body['hierarchy']['sectors'][0]['origin_km'],[12000000,0,0])

    def test_revision_pin_partial_error_and_unsupported_date(self):
        path='/api/positions/v1/sectors/synthetic:0'
        self.assertEqual(self.client.get(path,params={'at':AT,'revision':'old'}).status_code,409)
        self.client.post('/api/_test/control',json={'fail':'synthetic:0'})
        self.assertEqual(self.client.get(path,params={'at':AT,'revision':fixture.current_revision()}).status_code,422)
        self.assertEqual(self.client.get(path,params={'at':'2030-01-01T00:00:00Z','revision':fixture.current_revision()}).status_code,422)
        self.assertEqual(self.client.post('/api/_test/control',json={'unrecognized':1}).status_code,422)

    def test_production_app_never_installs_test_routes(self):
        from backend.app import app
        self.assertFalse(any('/_test/' in getattr(route,'path','') for route in app.routes))
