"""Offline centers against independently retrieved Horizons DE441 vectors."""
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.position_api import install_position_api
from data.ephemeris import Ephemeris, contract, parse_utc, UTC_START, UTC_STOP, TDB_START, TDB_STOP, TARGETS, REVISION


class PositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = Ephemeris()

    @classmethod
    def tearDownClass(cls):
        cls.engine.close()

    def test_independent_horizons_body_centers_at_twenty_tdb_dates(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/horizons_centers.json').read_text())
        self.assertEqual(fixture['reference_system'], 'ICRF')
        self.assertEqual(fixture['corrections'], 'NONE')
        self.assertEqual({s['id']: s['target'] for s in fixture['samples']}, TARGETS)
        maximum = 0
        samples = 0
        for body in fixture['samples']:
            self.assertIn('source: DE441', body['header'])
            self.assertEqual(len(body['rows']), 20)
            body_maximum = 0
            self.assertEqual([r['jd_tdb'] for r in body['rows']],
                             [r['jd_tdb'] for r in fixture['samples'][0]['rows']])
            for row in body['rows']:
                actual = self.engine.evaluate(jd_tdb=row['jd_tdb'], ids=[body['id']])['objects'][0]
                error = math.dist(actual['position'], row['position'])
                maximum = max(maximum, error)
                body_maximum = max(body_maximum, error)
                samples += 1
                with self.subTest(id=body['id'], jd=row['jd_tdb']):
                    self.assertEqual(actual['target'], body['target'])
                    self.assertLess(error, fixture['tolerance_km'])
            print(f"{body['id']}: max 3D error {body_maximum:.9f} km")
        print(f'\nDE440s vs independent Horizons DE441: max 3D error {maximum:.9f} km ({samples} vectors)')

    def test_time_roundtrip_reversal_and_unknown_centers(self):
        at = '2026-11-06T12:34:56.123456Z'
        initial = self.engine.evaluate(at=at)
        self.engine.evaluate(at='2000-01-01T00:00:00Z')
        self.engine.evaluate(at='2026-12-31T23:59:59Z')
        self.assertEqual(self.engine.evaluate(at=at), initial)
        same = self.engine.evaluate(jd_tdb=initial['jd_tdb'])
        for utc, tdb in zip(initial['objects'], same['objects']):
            self.assertLess(math.dist(utc['position'], tdb['position']), .001)
        unknown = self.engine.evaluate(at=at, ids=['unmeasured'])['objects'][0]
        self.assertIsNone(unknown['position'])
        self.assertIsNone(unknown['target'])
        self.assertEqual(unknown['status'], 'unknown')
        self.assertNotEqual(initial['objects'][1]['position'], initial['objects'][2]['position'])
        self.assertIsNone(contract()['accuracy'])
        self.assertIsNone(contract()['source_epoch'])

    def test_mercury_and_venus_are_body_centers_and_other_barycenters_stay_unknown(self):
        self.assertEqual(TARGETS['mercury'], 199)
        self.assertEqual(TARGETS['venus'], 299)
        initial = self.engine.evaluate(at='2026-11-06T12:00:00Z')
        by_id = {row['id']: row for row in initial['objects']}
        for oid, target in [('mercury', 199), ('venus', 299)]:
            self.assertEqual(self.engine.kernel[target].target, target)
            self.assertEqual(by_id[oid]['status'], 'computed')
            self.assertEqual(by_id[oid]['target'], target)
            for boundary in [TDB_START, TDB_STOP-1e-6]:
                edge = self.engine.evaluate(jd_tdb=boundary, ids=[oid])['objects'][0]
                self.assertTrue(all(math.isfinite(v) for v in edge['position']))
        self.engine.evaluate(at='2000-01-01T00:00:00Z')
        self.assertEqual(self.engine.evaluate(at='2026-11-06T12:00:00Z'), initial)
        unknown = self.engine.evaluate(jd_tdb=2451545, ids=['mars','jupiter','mercury_barycenter','venus_barycenter'])
        self.assertTrue(all(row['position'] is None and row['target'] is None for row in unknown['objects']))

    def test_utc_conversion_includes_leap_seconds(self):
        # Independent UTC -> TT reference: UTC+TAI_offset+32.184s.
        for at, offset in [('2000-01-01T12:00:00Z', 32), ('2017-01-01T12:00:00Z', 37)]:
            t = self.engine.timescale.from_datetime(parse_utc(at))
            jd = 2451545.0 if offset == 32 else 2457755.0
            self.assertAlmostEqual((t.tt-jd)*86400, offset+32.184, delta=.0001)
        self.assertEqual(parse_utc('2026-11-06T15:00:00+03:00'), parse_utc('2026-11-06T12:00:00Z'))
        self.assertEqual(parse_utc(UTC_START.isoformat()), UTC_START)

    def test_2027_utc_matches_pinned_iers_table_and_stops_at_expiry(self):
        from datetime import timedelta
        fixture=json.loads((Path(__file__).parent/'fixtures/utc_leap_support.json').read_text())
        self.assertEqual(UTC_STOP.date().isoformat(),fixture['table_expires'])
        self.assertFalse(fixture['december_2026_insertion'])
        samples=[*fixture['tai_minus_utc_seconds'][1:],['2027-01-01T00:00:00Z',37],['2027-06-27T00:00:00Z',37]]
        for at,offset in samples:
            date=parse_utc(at);t=self.engine.timescale.from_datetime(date)
            utc_jd=date.toordinal()+1721424.5
            self.assertAlmostEqual((t.tt-utc_jd)*86400,offset+32.184,delta=.0001)
            frame=self.engine.evaluate(at=at)
            equivalent=self.engine.evaluate(jd_tdb=frame['jd_tdb'])
            for a,b in zip(frame['objects'],equivalent['objects']):
                # A serialized binary64 JD has ~40 us spacing here; converting
                # full UTC to that scalar loses low time bits (not ephemeris error).
                self.assertLess(math.dist(a['position'],b['position']),.003)
        self.engine.evaluate(at=(UTC_STOP-timedelta(microseconds=1)).isoformat())
        for at in [UTC_STOP.isoformat(),'2027-07-01T00:00:00Z','2027-06-30T23:59:60Z']:
            with self.assertRaises(ValueError):self.engine.evaluate(at=at)

    def test_invalid_unsupported_or_ambiguous_time_is_never_a_snapshot(self):
        for at in ['', 'now', '2026-11-06', '2026-11-06T12:00:00', '2016-12-31T23:59:60Z',
                   '1999-12-31T23:59:59Z', UTC_STOP.isoformat(), 'badTtimestamp', '9999-12-31T23:59:59-23:59']:
            with self.subTest(at=at), self.assertRaises(ValueError):
                self.engine.evaluate(at=at)
        for kwargs in [{}, {'at':'2026-01-01T00:00:00Z','jd_tdb':2451545},
                       *({'jd_tdb':jd} for jd in [float('nan'),float('inf'),TDB_START-1,TDB_STOP])]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.engine.evaluate(**kwargs)

    def test_missing_or_changed_kernel_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'kernel.bsp'
            with self.assertRaises(FileNotFoundError):
                Ephemeris(path)
            path.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                Ephemeris(path)


class PositionAPITests(unittest.TestCase):
    def client(self):
        app = FastAPI()
        # Independent simple weak/list validator for this isolated router test.
        install_position_api(app, lambda supplied, etag: supplied is not None and
                             (supplied == '*' or etag in supplied))
        return TestClient(app)

    def test_fixed_camera_origin_is_independent_of_anchor_time_and_validated_before_etag(self):
        with self.client() as client:
            at='2020-01-01T00:00:00Z'
            vector=client.get('/api/positions/v1/objects/earth',params={'at':at}).json()['objects'][0]['position']
            query=dict(anchor='earth',dx=0,dy=0,dz=0,radius=1,at=at,ox=vector[0],oy=vector[1],oz=vector[2])
            near=client.get('/api/positions/v1/nearby',params=query)
            self.assertEqual(near.status_code,200)
            self.assertEqual(len(near.json()['sectors']),1)
            self.assertEqual(near.json()['query']['origin_km'],vector)
            # Anchor is irrelevant to the fixed physical camera, at either date.
            for date in [at,'2021-06-01T00:00:00Z']:
                a=client.get('/api/positions/v1/nearby',params={**query,'at':date}).json()
                b=client.get('/api/positions/v1/nearby',params={**query,'at':date,'anchor':'venus'}).json()
                self.assertEqual(a['sectors'],b['sectors'])
            for update in [{'ox':None},{'oy':'nan'},{'oz':1e14}]:
                bad={k:v for k,v in {**query,**update}.items() if v is not None}
                self.assertEqual(client.get('/api/positions/v1/nearby',params=bad,headers={'If-None-Match':'*'}).status_code,422)
            self.assertEqual(client.get('/api/positions/v1/nearby',params=query,headers={'If-None-Match':near.headers['etag']}).status_code,304)

    def test_versioned_contract_conditional_requests_and_unknown_positions(self):
        with self.client() as client:
            self.assertEqual(client.get('/api/positions/v1/contract').json()['version'], 'positions/1')
            url = '/api/positions/v1/sectors/solar:verified?at=2026-11-06T12:34:56Z'
            response = client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()['objects']), 5)
            self.assertEqual(response.json()['coordinates']['supported_ids'], list(TARGETS))
            self.assertEqual(response.json()['revision'], REVISION)
            self.assertEqual(response.headers['X-Coordinate-Contract'], 'positions/1')
            for validator in ['*',response.headers['etag'], 'W/'+response.headers['etag']]:
                cached = client.get(url, headers={'If-None-Match': validator})
                self.assertEqual(cached.status_code, 304)
                self.assertEqual(cached.content,b'')
            other = client.get(url.replace('12:34:56','12:34:57'))
            self.assertNotEqual(other.headers['etag'],response.headers['etag'])
            unknown = client.get('/api/positions/v1/objects/proxima_b?jd_tdb=2451545').json()
            self.assertIsNone(unknown['objects'][0]['position'])
            for query in ['', '?at=', '?at='+UTC_STOP.isoformat().replace('+00:00','Z'), '?jd_tdb=nan',
                          '?at=2026-01-01T00:00:00Z&jd_tdb=2451545', '?jd_tdb=banana']:
                with self.subTest(query=query):
                    self.assertEqual(client.get('/api/positions/v1/sectors/solar:verified'+query,
                        headers={'If-None-Match':'*'}).status_code,422)
            self.assertEqual(client.get('/api/positions/v1/objects/'+'x'*513+'?jd_tdb=2451545').status_code,422)

    def test_neighborhood_recomputes_moving_bounds_and_obeys_query_limits(self):
        with self.client() as client:
            base='/api/positions/v1/nearby?anchor=earth&dx=0&dy=0&dz=0&radius=0&'
            for date in ['2000-01-01T00:00:00Z','2026-11-06T12:00:00Z']:
                response=client.get(base+'at='+date)
                self.assertEqual(response.status_code,200)
                body=response.json()
                self.assertEqual(body['objects'],[])
                self.assertEqual(body['sectors'][0]['id'],'solar:verified')
                cached=client.get(base+'at='+date,headers={'If-None-Match':response.headers['etag']})
                self.assertEqual(cached.status_code,304)
            empty=client.get(base.replace('dx=0','dx=1000000000000')+'jd_tdb=2451545').json()
            self.assertEqual(empty['sectors'],[])
            for query in [base.replace('anchor=earth','anchor=unverified'),base.replace('radius=0','radius=-1'),
                          base.replace('dx=0','dx=nan'),base.replace('dy=0','dy=1e14')]:
                self.assertEqual(client.get(query+'jd_tdb=2451545',headers={'If-None-Match':'*'}).status_code,422)
            self.assertEqual(client.get(base+'at=1999-01-01T00:00:00Z',headers={'If-None-Match':'*'}).status_code,422)

    def test_new_centers_have_individual_routes_and_moving_neighborhoods(self):
        with self.client() as client:
            for oid, target in [('mercury',199),('venus',299)]:
                for jd in [2451545,2461350.5]:
                    response = client.get(f'/api/positions/v1/objects/{oid}?jd_tdb={jd}')
                    self.assertEqual(response.status_code,200)
                    row = response.json()['objects'][0]
                    self.assertEqual((row['id'],row['target'],row['status']),(oid,target,'computed'))
                    self.assertEqual(client.get(f'/api/positions/v1/objects/{oid}?jd_tdb={jd}',
                        headers={'If-None-Match':response.headers['etag']}).status_code,304)
                    near = client.get(f'/api/positions/v1/nearby?anchor={oid}&dx=0&dy=0&dz=0&radius=0&jd_tdb={jd}').json()
                    self.assertEqual(near['sectors'][0]['object_count'],5)
                    for axis, value in enumerate(row['position']):
                        self.assertLessEqual(near['sectors'][0]['min'][axis],value)
                        self.assertGreaterEqual(near['sectors'][0]['max'][axis],value)
                rejected = client.get(f'/api/positions/v1/objects/{oid}?at='+UTC_STOP.isoformat().replace('+00:00','Z'),
                    headers={'If-None-Match':'*'})
                self.assertEqual(rejected.status_code,422)
            unknown = client.get('/api/positions/v1/objects/mars?jd_tdb=2451545').json()
            self.assertIsNone(unknown['objects'][0]['position'])

    def test_unavailable_coefficients_return_503_without_fallback(self):
        with self.client() as client, patch('backend.position_api.Ephemeris',side_effect=OSError('missing')):
            response=client.get('/api/positions/v1/sectors/solar:verified?jd_tdb=2451545')
            self.assertEqual(response.status_code,503)
            self.assertEqual(response.headers['cache-control'],'no-store')
