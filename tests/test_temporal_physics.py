"""Independent affine oracles for conservative requested-time selection.

Primitive fixture trajectories below are the oracle. They never read published
envelopes or synthetic_record() to derive expected positions or intersections.
The 100 independent real Horizons vectors remain in tests.test_positions.
"""
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.ephemeris import TDB_START, TDB_STOP
from data.temporal_index import (
    EPOCH_JD, SCHEMA, TemporalIndex, build_synthetic, ensure_real, normalize_time,
)


# A publication epoch deliberately different from the normal generator epoch.
EPOCH = EPOCH_JD + .125
TRAJECTORIES = {
    'entrant': ('test:entrant', (-20., 0., 0.), (10., 0., 0.)),
    'reverse': ('test:reverse', (20., 10., 0.), (-10., 0., 0.)),
    'tangent': ('test:tangent', (-20., 5., 0.), (10., 0., 0.)),
}


def oracle_positions(jd):
    return {oid: [p + v * (jd - EPOCH) for p, v in zip(start, velocity)]
            for oid, (_, start, velocity) in TRAJECTORIES.items()}


def oracle_sectors(jd, center, radius):
    # Each focused sector has one known point; null companion is not a point.
    return {TRAJECTORIES[oid][0] for oid, vector in oracle_positions(jd).items()
            if math.dist(center, vector) <= radius}


def build_focused(path):
    """Publish explicit two-bucket input, without the production generator."""
    metadata = {
        'schema': 1, 'profile': 'synthetic-affine', 'count': 4,
        'interval': [EPOCH, EPOCH + 4], 'bucket_days': 2, 'epoch_jd': EPOCH,
        'revision': 'synthetic-independent-affine/1',
        'temporal_revision': 'synthetic-independent-affine/1',
        'registry_revision': 'synthetic-independent-affine/1',
        'coordinates': {
            'version': 'positions/1', 'representation': 'simulation_position',
            'reference_system': 'ICRF', 'origin': 'solar_system_barycenter',
            'unit': 'km', 'time_scale': 'TDB', 'accuracy': None,
            'source': 'SYNTHETIC independent affine test; no measured astronomy',
            'synthetic': True, 'revision': 'synthetic-independent-affine/1',
        },
    }
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.executemany('INSERT INTO metadata VALUES (?,?)',
                       [(key, json.dumps(value)) for key, value in metadata.items()])
        for n, (oid, (sid, start, velocity)) in enumerate(TRAJECTORIES.items()):
            db.execute('INSERT INTO sectors VALUES (?,?)', (sid, 2 if n == 0 else 1))
            db.execute('INSERT INTO bodies VALUES (?,?,?,?,?,?,?,?,?)',
                       (oid, n, sid, *start, *velocity))
            for bucket in range(2):
                endpoints = [[p + v * dt for p, v in zip(start, velocity)]
                             for dt in (2 * bucket, 2 * bucket + 2)]
                bounds = [value for axis in range(3)
                          for value in (min(point[axis] for point in endpoints),
                                        max(point[axis] for point in endpoints))]
                rowid = n * 2 + bucket + 1
                db.execute('INSERT INTO envelopes VALUES (?,?,?)', (rowid, sid, bucket))
                db.execute('INSERT INTO bounds VALUES (?,?,?,?,?,?,?,?,?)',
                           (rowid, *bounds, bucket, bucket))
        db.execute('INSERT INTO bodies VALUES (?,?,?,?,?,?,?,?,?)',
                   ('unknown', 3, 'test:entrant', None, None, None, None, None, None))
    return TemporalIndex(path)


class TemporalPhysicsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.index = build_focused(Path(self.temporary.name) / 'focused.sqlite')

    def exact_selection(self, jd, center, radius):
        """Oracle-only narrow phase; server may retain swept false positives."""
        with self.index.snapshot() as snapshot:
            candidates = snapshot.candidates(center, radius, jd)
            selected = set()
            for candidate in candidates:
                rows = snapshot.positions(snapshot.members(candidate['id']), jd)
                if any(row['position'] is not None and math.dist(row['position'], center) <= radius
                       for row in rows):
                    selected.add(candidate['id'])
            return {row['id'] for row in candidates}, selected

    def test_crossing_entrance_exit_reversal_and_bucket_seams(self):
        center = [0, 0, 0]
        seam = EPOCH + 2
        dates = [EPOCH, EPOCH + 1, math.nextafter(seam, -math.inf), seam,
                 math.nextafter(seam, math.inf), EPOCH + 3,
                 math.nextafter(EPOCH + 4, -math.inf)]
        for jd in dates + list(reversed(dates)):
            for radius in (0, 5, 10, 25):
                with self.subTest(jd=jd, radius=radius):
                    candidates, selected = self.exact_selection(jd, center, radius)
                    expected = oracle_sectors(jd, center, radius)
                    self.assertLessEqual(expected, candidates, 'candidate phase omitted a true member')
                    self.assertEqual(selected, expected)
        self.assertNotIn('test:entrant', self.exact_selection(EPOCH, center, 0)[1])
        self.assertIn('test:entrant', self.exact_selection(seam, center, 0)[1])
        self.assertNotIn('test:entrant', self.exact_selection(EPOCH + 3, center, 0)[1])

    def test_tangency_is_inclusive_and_just_outside_is_excluded(self):
        jd = EPOCH + 2
        self.assertIn('test:tangent', self.exact_selection(jd, [0, 0, 0], 5)[1])
        self.assertNotIn('test:tangent', self.exact_selection(jd, [0, 0, 0],
                                                          math.nextafter(5., 0.))[1])
        self.assertIn('test:reverse', self.exact_selection(jd, [0, 10, 0], 0)[1])

    def test_exact_positions_unknown_null_and_revisited_date(self):
        for jd in (EPOCH, EPOCH + 3.125, EPOCH + 2, EPOCH):
            with self.index.snapshot() as snapshot:
                for oid, expected in oracle_positions(jd).items():
                    row = snapshot.object(oid)
                    actual = snapshot.positions([row], jd)[0]
                    self.assertEqual(actual['position'], expected)
                    self.assertEqual(actual['status'], 'computed')
                self.assertIsNone(snapshot.object('unsupported'))
                unknown = snapshot.positions([snapshot.object('unknown')], jd)[0]
                self.assertIsNone(unknown['position'])
                self.assertEqual(unknown['status'], 'unknown')
                self.assertEqual(len(snapshot.members('test:entrant')), 2)
                self.assertIsNone(snapshot.members('unsupported'))
        # Null does not become [0,0,0] at the epoch or force a sector into view.
        self.assertEqual(self.exact_selection(EPOCH, [0, 0, 0], 0)[1], set())

    def test_unsupported_time_never_reuses_a_supported_bucket(self):
        with self.index.snapshot() as snapshot:
            for jd in (EPOCH - 1, EPOCH + 4, float('nan'), float('inf')):
                with self.subTest(jd=jd), self.assertRaises(ValueError):
                    snapshot.candidates([0, 0, 0], 1, jd)
        for kwargs in ({}, {'at': '2026-01-01T00:00:00Z', 'jd_tdb': EPOCH},
                       {'at': '2027-06-28T00:00:00Z'}, {'jd_tdb': TDB_START - 1},
                       {'jd_tdb': TDB_STOP}, {'jd_tdb': float('nan')}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                normalize_time(**kwargs)

    def test_generated_publication_has_no_omissions_against_independent_formula(self):
        index = build_synthetic(Path(self.temporary.name) / 'generated.sqlite', 256)
        # Explicit values independently reconstructed from documented generator;
        # no synthetic_record() or envelope data supplies expected positions.
        for n in (0, 63, 126, 128, 190, 254):
            sector, offset = divmod(n, 128)
            p0 = [(0 if sector < 16 else (sector - 15) * 1_000_000) + (offset - 63.5) * 1000,
                  0, (offset % 8 - 3.5) * 1000]
            velocity = [100 if sector % 2 == 0 else -100, (sector % 3 - 1) * 10, 0]
            for jd in (TDB_START, TDB_START + 365,
                       math.nextafter(TDB_START + 365, -math.inf), EPOCH,
                       math.nextafter(TDB_STOP, -math.inf)):
                expected = [p + v * (jd - EPOCH_JD) for p, v in zip(p0, velocity)]
                with index.snapshot() as snapshot:
                    candidates = snapshot.candidates(expected, 0, jd)
                    self.assertIn(f'temporal:{sector:07d}', {row['id'] for row in candidates})
                    actual = snapshot.positions([snapshot.object(f'synthetic-{n:07d}')], jd)[0]
                    self.assertEqual(actual['position'], expected)
        with index.snapshot() as snapshot:
            for n in (127, 255):
                self.assertIsNone(snapshot.positions([snapshot.object(f'synthetic-{n:07d}')], EPOCH)[0]['position'])

    def test_real_lane_is_unconditional_for_only_five_existing_centers(self):
        index = ensure_real(Path(self.temporary.name) / 'real.sqlite')
        with index.snapshot() as snapshot:
            self.assertEqual(snapshot.metadata['profile'], 'real-five')
            expected = {'sun', 'earth', 'moon', 'mercury', 'venus'}
            self.assertEqual({row['id'] for row in snapshot.members('solar:verified')}, expected)
            for jd in (TDB_START, EPOCH, math.nextafter(TDB_STOP, -math.inf)):
                for center in ([0, 0, 0], [1e13, -1e13, 1e13]):
                    self.assertEqual(snapshot.candidates(center, 0, jd),
                                     [{'id': 'solar:verified', 'object_count': 5}])
            self.assertIsNone(snapshot.object('mars'))


class TemporalPhysicsHTTPTests(unittest.TestCase):
    """Transport integration of the independent oracle, run in the unit image."""

    setUp = TemporalPhysicsTests.setUp

    def client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from backend.position_api import install_position_api
        app = FastAPI()
        install_position_api(app, lambda supplied, etag: supplied is not None and
                             (supplied == '*' or etag in supplied),
                             temporal_index_factory=lambda: self.index)
        return TestClient(app)

    def query(self, jd, radius=0, anchor='entrant'):
        return dict(anchor=anchor, dx=0, dy=0, dz=0, radius=radius,
                    ox=0, oy=0, oz=0, jd_tdb=jd)

    def test_http_candidates_cover_oracle_and_sector_vectors_match_time(self):
        with self.client() as client:
            dates = (EPOCH, EPOCH + 1, math.nextafter(EPOCH + 2, -math.inf),
                     EPOCH + 2, math.nextafter(EPOCH + 2, math.inf), EPOCH + 3,
                     EPOCH + 1)
            for jd in dates:
                for radius in (0, 5, 10):
                    query = self.query(jd, radius)
                    manifest_response = client.get('/api/positions/v1/nearby', params=query)
                    self.assertEqual(manifest_response.status_code, 200, manifest_response.text)
                    manifest = manifest_response.json()
                    candidates = {row['id'] for row in manifest['sectors']}
                    self.assertLessEqual(oracle_sectors(jd, [0, 0, 0], radius), candidates)
                    self.assertEqual(manifest['objects'], [])
                    self.assertEqual(manifest['jd_tdb'], jd)
                    self.assertIsNone(manifest['evaluated_at'])
                    self.assertTrue(manifest['selection']['false_positives_possible'])
                    for candidate in manifest['sectors']:
                        response = client.get('/api/positions/v1/sectors/' + candidate['id'],
                                              params={'jd_tdb': jd, 'revision': manifest['revision'],
                                                      'temporal_revision': manifest['temporal_revision']})
                        self.assertEqual(response.status_code, 200, response.text)
                        frame = response.json()
                        self.assertEqual(frame['registry_revision'], manifest['registry_revision'])
                        self.assertEqual(frame['temporal_revision'], manifest['temporal_revision'])
                        self.assertEqual(frame['jd_tdb'], jd)
                        for row in frame['objects']:
                            if row['id'] == 'unknown':
                                self.assertIsNone(row['position'])
                                self.assertEqual(row['status'], 'unknown')
                            else:
                                self.assertEqual(row['position'], oracle_positions(jd)[row['id']])
                        hierarchy = frame['hierarchy']
                        self.assertEqual(hierarchy['jd_tdb'], jd)
                        self.assertEqual(hierarchy['reference_system'], 'ICRF')
                        self.assertEqual(hierarchy['unit'], 'km')

    def test_http_fixed_origin_revision_and_invalid_time_precede_etag(self):
        with self.client() as client:
            url = '/api/positions/v1/nearby'
            query = self.query(EPOCH + 2, 5)
            response = client.get(url, params=query)
            self.assertEqual(response.status_code, 200, response.text)
            manifest = response.json()
            other = client.get(url, params={**query, 'anchor': 'reverse'}).json()
            self.assertEqual(manifest['sectors'], other['sectors'])
            self.assertEqual(client.get(url, params=query,
                                        headers={'If-None-Match': response.headers['etag']}).status_code, 304)
            for update in ({'revision': 'stale'}, {'temporal_revision': 'stale'}):
                bad = client.get(url, params={**query, **update}, headers={'If-None-Match': '*'})
                self.assertEqual(bad.status_code, 409)
                self.assertEqual(bad.headers['cache-control'], 'no-store')
            for update in ({'jd_tdb': TDB_STOP}, {'jd_tdb': 'nan'}, {'anchor': 'unsupported'},
                           {'ox': 'nan'}, {'radius': -1}):
                self.assertEqual(client.get(url, params={**query, **update},
                                            headers={'If-None-Match': '*'}).status_code, 422)
            unknown = client.get('/api/positions/v1/objects/unsupported', params={'jd_tdb': EPOCH}).json()
            self.assertIsNone(unknown['objects'][0]['position'])
            self.assertEqual(unknown['objects'][0]['status'], 'unknown')


if __name__ == '__main__':
    unittest.main()
