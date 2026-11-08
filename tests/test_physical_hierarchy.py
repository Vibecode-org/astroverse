"""Wire hierarchy and preserved offline numerical references; no new source assets."""
import json
from pathlib import Path
import unittest
from data.ephemeris import Ephemeris, REVISION
from data.physical_hierarchy import attach_hierarchy
import tests.test_positions as position_tests


class PhysicalHierarchyTests(unittest.TestCase):
    def test_all_horizons_vectors_keep_canonical_centers_and_explicit_time_binding(self):
        samples=json.loads((Path(__file__).parent/'fixtures/horizons_centers.json').read_text())['samples']
        engine=Ephemeris()
        try:
            for body in samples:
                for reference in body['rows']:
                    frame=engine.evaluate(jd_tdb=reference['jd_tdb'],ids=[body['id']])
                    h=frame['hierarchy'];row=frame['objects'][0]
                    self.assertEqual(h['version'],'physical-hierarchy/1')
                    for key in ['revision','jd_tdb','evaluated_at']:self.assertEqual(h[key],frame[key])
                    self.assertEqual(h['bodies'][0]['offset_km'],row['position'])
                    self.assertEqual(h['systems'][0]['sector_id'],h['sectors'][0]['id'])
                    self.assertEqual(h['bodies'][0]['system_id'],h['systems'][0]['id'])
                    self.assertEqual(h['sectors'][0]['origin_km'],[0,0,0])
                    self.assertEqual(h['systems'][0]['offset_km'],[0,0,0])
                    self.assertIsNone(frame['coordinates']['accuracy'])
            unknown=engine.evaluate(at='2026-11-06T12:34:56Z',ids=['unmeasured'])
            self.assertIsNone(unknown['hierarchy']['bodies'][0]['offset_km'])
            self.assertIsNone(unknown['hierarchy']['bodies'][0]['system_id'])
            self.assertEqual(unknown['hierarchy']['evaluated_at'],unknown['evaluated_at'])
            # Hierarchy arrays do not alias authoritative input vectors.
            frame['hierarchy']['bodies'][0]['offset_km'][0]=0
            self.assertNotEqual(frame['objects'][0]['position'][0],0)
        finally:engine.close()

    def test_bounds_and_synthetic_fixture_independent_arithmetic(self):
        with self.assertRaises(ValueError):attach_hierarchy({'objects':[{}]*4097})
        f=json.loads((Path(__file__).parent/'fixtures/physical_hierarchy_synthetic.json').read_text())['frame']
        h=f['hierarchy'];systems={r['id']:r for r in h['systems']};sectors={r['id']:r for r in h['sectors']}
        for body,row in zip(h['bodies'],f['objects']):
            system=systems[body['system_id']];sector=sectors[system['sector_id']]
            expected=None if sector['origin_km'] is None else [sum(v[a] for v in [sector['origin_km'],system['offset_km'],body['offset_km']]) for a in range(3)]
            self.assertEqual(expected,row['position'])

    def test_http_addition_changes_revision_and_preserves_snapshot_and_unknown_semantics(self):
        with position_tests.PositionAPITests().client() as client:
            url='/api/positions/v1/objects/earth?jd_tdb=2451545'
            r=client.get(url);self.assertEqual(r.status_code,200)
            self.assertIn('hierarchy1',REVISION)
            self.assertEqual(r.json()['hierarchy']['revision'],REVISION)
            self.assertEqual(client.get(url,headers={'If-None-Match':r.headers['etag']}).status_code,304)
            nearby=client.get('/api/positions/v1/nearby?anchor=earth&dx=0&dy=0&dz=0&radius=0&jd_tdb=2451545').json()
            self.assertNotIn('hierarchy',nearby)
            self.assertEqual(nearby['objects'],[])

    def test_positions_pin_revision_before_validators_and_preserve_unpinned_clients(self):
        with position_tests.PositionAPITests().client() as client:
            for path in ['/sectors/solar:verified','/objects/earth','/nearby?anchor=earth&dx=0&dy=0&dz=0&radius=0']:
                url='/api/positions/v1'+path+('&' if '?' in path else '?')+'jd_tdb=2451545'
                baseline=client.get(url);self.assertEqual(baseline.status_code,200)
                pinned=client.get(url+'&revision='+REVISION);self.assertEqual(pinned.json(),baseline.json())
                cached=client.get(url+'&revision='+REVISION,headers={'If-None-Match':baseline.headers['etag']})
                self.assertEqual(cached.status_code,304)
                for validator in ['*',baseline.headers['etag']]:
                    stale=client.get(url+'&revision=old',headers={'If-None-Match':validator})
                    self.assertEqual(stale.status_code,409)
                    self.assertEqual(stale.json()['detail']['code'],'position_revision_changed')
                self.assertEqual(client.get(url+'&revision='+'x'*257).status_code,422)
