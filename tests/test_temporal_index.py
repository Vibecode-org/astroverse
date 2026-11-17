"""Bounded temporal index and immutable-publication regression checks."""
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from data.temporal_index import (TemporalIndex, build_synthetic, ensure_real,
                                 EPOCH_JD, MAX_MEMBERS, MAX_SECTORS, normalize_time)


class TemporalIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.temp.name) / 'temporal.sqlite'
        cls.index = build_synthetic(cls.path, 2304)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_bounded_dense_sparse_empty_and_overflow(self):
        with self.index.snapshot() as snapshot:
            dense = snapshot.candidates([0, 0, 0], 100000, EPOCH_JD)
            self.assertEqual({row['id'] for row in dense}, {f'temporal:{i:07d}' for i in range(16)})
            self.assertEqual(sum(row['object_count'] for row in dense), 2048)
            sparse = snapshot.candidates([2e6, 0, 0], 100000, EPOCH_JD)
            self.assertEqual([row['id'] for row in sparse], ['temporal:0000017'])
            self.assertEqual(snapshot.candidates([0, 1e9, 0], 100000, EPOCH_JD), [])
            statements = []
            snapshot.db.set_trace_callback(statements.append)
            with self.assertRaises(OverflowError):
                snapshot.candidates([0, 0, 0], 1e12, EPOCH_JD)
            self.assertTrue(any('LIMIT 17' in sql for sql in statements))
            self.assertFalse(any('FROM bodies' in sql for sql in statements))

    def test_members_exact_time_null_and_unknown(self):
        with self.index.snapshot() as snapshot:
            rows = snapshot.members('temporal:0000017')
            self.assertEqual(len(rows), MAX_MEMBERS)
            self.assertIsNone(snapshot.members('missing'))
            self.assertIsNone(snapshot.object('missing'))
            for jd in (EPOCH_JD, EPOCH_JD+1, EPOCH_JD-1, EPOCH_JD):
                result = snapshot.positions(rows, jd)
                for row in result:
                    n = int(row['id'].rsplit('-', 1)[1]); s, i = divmod(n, 128)
                    if i == 127:
                        self.assertIsNone(row['position'])
                        self.assertEqual(row['status'], 'unknown')
                    else:
                        expected = [(s-15)*1e6+(i-63.5)*1000-100*(jd-EPOCH_JD),
                                    (s%3-1)*10*(jd-EPOCH_JD), (i%8-3.5)*1000]
                        self.assertEqual(row['position'], expected)

    def test_missing_or_invalid_publication_fails_closed(self):
        with self.assertRaises(sqlite3.Error):
            TemporalIndex(Path(self.temp.name) / 'missing.sqlite')
        bad = Path(self.temp.name) / 'bad.sqlite'
        bad.write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.Error):
            TemporalIndex(bad)
        with self.assertRaises(ValueError):
            build_synthetic(bad, 0)

    def test_atomic_replacement_preserves_old_readers_and_failure_keeps_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'index.sqlite'
            index = build_synthetic(path, 128)
            before = path.read_bytes()
            with patch('data.temporal_index.os.replace', side_effect=OSError('injected')):
                with self.assertRaises(OSError):
                    build_synthetic(path, 256)
            self.assertEqual(path.read_bytes(), before)
            with index.snapshot() as old:
                old_revision = old.metadata['revision']
                build_synthetic(path, 256)
                self.assertEqual(old.metadata['revision'], old_revision)
                self.assertIsNone(old.object('synthetic-0000128'))
                with index.snapshot() as new:
                    self.assertNotEqual(new.metadata['revision'], old_revision)
                    self.assertIsNotNone(new.object('synthetic-0000128'))

    def test_real_candidates_are_unconditional_five_and_time_is_validated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'real.sqlite'
            index = ensure_real(path)
            self.assertEqual(ensure_real(path).metadata, index.metadata)
            with index.snapshot() as snapshot:
                for center in ([0, 0, 0], [1e12, 1e12, 1e12]):
                    self.assertEqual(snapshot.candidates(center, 0, EPOCH_JD),
                                     [{'id':'solar:verified','object_count':5}])
                self.assertEqual(len(snapshot.members('solar:verified')), 5)
                with self.assertRaises(ValueError):
                    snapshot.candidates([0, 0, 0], 0, 0)
        for arguments in ({}, {'at':'now'}, {'jd_tdb':float('nan')},
                          {'at':'2026-01-01T00:00:00Z','jd_tdb':EPOCH_JD}):
            with self.assertRaises(ValueError):
                normalize_time(**arguments)
        jd, at = normalize_time(at='2026-01-01T00:00:00Z')
        self.assertTrue(math.isfinite(jd))
        self.assertEqual(at,'2026-01-01T00:00:00+00:00')
