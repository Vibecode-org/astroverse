"""Failure injection, numerical boundaries, CLI and independent spatial oracle."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stderr, redirect_stdout
import copy
import io
import json
import math
from pathlib import Path
import random
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from data.sectors import SectorIndex, build_sector_index, physical_position
from tests.test_sectors import star

ROOT = Path(__file__).resolve().parents[1]


class SectorEdgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sectors.sqlite"

    def build(self, objects=None, **options):
        build_sector_index(self.path, objects if objects is not None else [star("a", 10)], **options)
        return SectorIndex(self.path)

    def test_bad_configuration_types_and_float_extremes(self):
        for key, values in {
            "cell_size_ly": [None, "32", True, -1, math.nan, 10**1000, 1e39, 5e-324],
            "max_objects": [None, "3", True, 1.5, -1],
            "max_depth": [None, "3", True, 1.5],
        }.items():
            for value in values:
                with self.subTest(key=key, value=str(value)[:20]), self.assertRaises(ValueError):
                    self.build(**{key: value})

    def test_small_cells_and_excessive_bounds_fail_without_replacing_artifact(self):
        self.build()
        old = self.path.read_bytes()
        for objects, options in [([star("a", 1)], dict(cell_size_ly=1e-320, max_depth=0)),
                                 ([star("a", 1e39)], {}),
                                 ([star("a", 2.9e38)], dict(cell_size_ly=2e38))]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.build(objects, **options)
            self.assertEqual(self.path.read_bytes(), old)

    def test_physical_input_validation_and_frame_preference(self):
        for distance in [-1, True, "1", math.inf, math.nan, 10**1000]:
            with self.subTest(distance=str(distance)[:20]), self.assertRaises(ValueError):
                physical_position(star("a", distance))
        for field, value in [("ra", -1), ("ra", 24), ("ra", "1"),
                             ("dec", 91), ("dec", True), ("galactic_l", 360),
                             ("galactic_l", math.nan), ("galactic_b", -91)]:
            obj = (star("a", 1) if field in ("ra", "dec") else
                   dict(distance_ly=1, galactic_l=0, galactic_b=0))
            obj[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                physical_position(obj)
        obj = star("both", 1, galactic_l=90, galactic_b=0)
        self.assertEqual(physical_position(obj), ("equatorial", 1, 0, 0))
        obj["dec"] = None
        self.assertEqual(physical_position(obj)[0], "galactic")
        obj["galactic_b"] = None
        self.assertIsNone(physical_position(obj))

    def test_invalid_query_shapes_and_numeric_extremes(self):
        index = self.build()
        for center in [None, 1, "abc", {1, 2, 3}, {"x": 0, "y": 0, "z": 0},
                       [], [0, 0, 0, 0], [None, 0, 0], [math.inf, 0, 0], [10**1000, 0, 0]]:
            with self.subTest(center=str(center)[:30]), self.assertRaises(ValueError):
                index.nearby("local", "equatorial", center, 1)
        for radius in [None, True, "1", -1, math.nan, 10**1000]:
            with self.subTest(radius=str(radius)[:30]), self.assertRaises(ValueError):
                index.nearby("local", "equatorial", [0, 0, 0], radius)
        self.assertEqual(len(index.nearby("local", "equatorial", [0, 0, 0], 1e308)), 1)

    def test_unknown_root_keeps_located_descendants_unlocated(self):
        child = star("child", 10, parent="root")
        index = self.build([child, star("root", None)])
        self.assertEqual(index.locate("child"), "local:unlocated")
        self.assertEqual(index.nearby("local", "equatorial", (10, 0, 0), 1), [])

    def test_octants_depth_zero_and_split_merge_revisions(self):
        objects = []
        for i, xyz in enumerate((x, y, z) for x in (4, 24) for y in (4, 24) for z in (4, 24)):
            x, y, z = xyz
            obj = star(str(i), math.hypot(*xyz), ra=math.degrees(math.atan2(z, x)) / 15)
            obj["dec"] = math.degrees(math.atan2(y, math.hypot(x, z)))
            objects.append(obj)
        index = self.build(objects, max_objects=1)
        self.assertEqual(len(index.sectors()), 8)
        self.assertEqual({s["id"].rsplit("/", 1)[-1] for s in index.sectors()}, set(map(str, range(8))))
        old_ids = {s["id"] for s in index.sectors()}
        merged = self.build(objects, max_objects=1, max_depth=0)
        self.assertEqual(len(merged.sectors()), 1)
        self.assertFalse(old_ids & {s["id"] for s in merged.sectors()})

    def test_spatial_queries_match_full_scan_for_seeded_random_catalog(self):
        rng = random.Random(137)
        objects = [dict(star(str(i), rng.uniform(0, 250), ra=rng.uniform(0, 24)),
                        dec=rng.uniform(-90, 90)) for i in range(240)]
        original = copy.deepcopy(objects)
        index = self.build(objects, cell_size_ly=17.3, max_objects=2)
        self.assertEqual(objects, original)
        leaves = index.sectors()
        for _ in range(100):
            center = tuple(rng.uniform(-200, 200) for _ in range(3))
            radius = rng.uniform(0, 100)
            expected = set()
            for s in leaves:
                closest = tuple(min(s[f"max_{a}"], max(s[f"min_{a}"], v))
                                for a, v in zip("xyz", center))
                if math.dist(center, closest) <= radius:
                    expected.add(s["id"])
            self.assertEqual({s["id"] for s in index.nearby("local", "equatorial", center, radius)},
                             expected)
        # No root may disappear because the float32 accelerator rounded a bound.
        for obj in objects:
            position = physical_position(obj)[1:]
            self.assertIn(index.locate(obj["id"]),
                          {s["id"] for s in index.nearby("local", "equatorial", position, 0)})

    def test_shared_faces_float32_rounding_and_zero_radius_queries(self):
        for boundary in [32., 0.1, 12345.6789]:
            objects = [star(str(i), d) for i, d in enumerate(
                [math.nextafter(boundary, 0), boundary, math.nextafter(boundary, math.inf)])]
            index = self.build(objects, cell_size_ly=boundary)
            for obj in objects:
                hits = index.nearby("local", "equatorial", (obj["distance_ly"], 0, 0), 0)
                self.assertIn(index.locate(obj["id"]), {s["id"] for s in hits})
            self.assertEqual(sum(s["object_count"] for s in index.sectors()), 3)

    def test_reader_readonly_independent_results_and_concurrent_reads(self):
        self.path = self.path.with_name("каталог #? ' .sqlite")
        obj = star("x'; DROP TABLE sectors;--", 10, facts=["one"])
        index = self.build([obj])
        sid = index.locate(obj["id"])
        self.assertIsNone(index.locate("' OR 1=1 --"))
        result = index.objects(sid)
        result[0]["facts"].append("mutated")
        self.assertEqual(index.objects(sid), [obj])
        with index._connect() as db, self.assertRaises(sqlite3.OperationalError):
            db.execute("DELETE FROM objects")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: index.objects(sid), range(16)))
        self.assertTrue(all(r == [obj] for r in results))

    def test_reader_rejects_unknown_version_missing_and_corrupt_files(self):
        with self.assertRaises(sqlite3.OperationalError):
            SectorIndex(self.path)
        self.assertFalse(self.path.exists())
        self.build()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
            db.commit()
        with self.assertRaisesRegex(ValueError, "schema version"):
            SectorIndex(self.path)
        self.path.write_bytes(b"not sqlite")
        with self.assertRaises(sqlite3.DatabaseError):
            SectorIndex(self.path)

    def test_failure_allocating_temporary_file_does_not_touch_old_index(self):
        self.build()
        previous = self.path.read_bytes()
        with patch("data.sectors.tempfile.NamedTemporaryFile", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.build()
        self.assertEqual(self.path.read_bytes(), previous)

    def test_database_open_and_atomic_replace_failures_clean_up(self):
        self.build()
        previous = self.path.read_bytes()
        for target in ["data.sectors.sqlite3.connect", "data.sectors.Path.replace"]:
            with self.subTest(target=target), patch(target, side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    self.build()
            self.assertEqual(self.path.read_bytes(), previous)
            self.assertEqual(list(Path(self.tmp.name).iterdir()), [self.path])

    def test_commit_failure_rolls_back_temporary_database_and_preserves_previous_index(self):
        self.build()
        before = self.path.read_bytes()
        connect = sqlite3.connect

        class FullDisk(sqlite3.Connection):
            def commit(self):
                raise sqlite3.OperationalError("database or disk is full")

        with patch("data.sectors.sqlite3.connect", side_effect=lambda *args, **kw: connect(*args, **kw, factory=FullDisk)):
            with self.assertRaises(sqlite3.OperationalError):
                self.build([star("replacement", 10)])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [self.path])

    def test_deep_parent_family_does_not_recurse_or_split_across_sectors(self):
        objects = [star("0", 10)] + [star(str(i), None, parent=str(i - 1)) for i in range(1, 1100)]
        index = self.build(list(reversed(objects)), max_objects=1)
        self.assertEqual(len(index.sectors()), 1)
        leaf = index.sectors()[0]
        self.assertEqual(leaf["system_count"], 1)
        self.assertEqual(leaf["object_count"], 1100)
        self.assertEqual(index.locate("1099"), index.locate("0"))

    def test_cli_success_and_source_preservation(self):
        source = Path(self.tmp.name) / "input.json"
        source.write_text(json.dumps([star("a", 10)]))
        before = source.read_bytes()
        out = io.StringIO()
        with patch.object(sys, "argv", ["sectors", str(source), str(self.path),
                                        "--cell-size-ly", "16", "--max-objects", "2"]), redirect_stdout(out):
            runpy.run_path(str(ROOT / "data/sectors.py"), run_name="__main__")
        self.assertEqual(json.loads(out.getvalue())["cell_size_ly"], 16)
        self.assertEqual(SectorIndex(self.path).metadata["object_count"], 1)
        self.assertEqual(source.read_bytes(), before)

    def test_cli_rejects_overwriting_source_and_wrong_extension(self):
        for destination in [ROOT / "data/catalog_seed.json", self.path.with_suffix(".json")]:
            with patch.object(sys, "argv", ["sectors", str(ROOT / "data/catalog_seed.json"),
                                            str(destination)]), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    runpy.run_path(str(ROOT / "data/sectors.py"), run_name="__main__")
            self.assertEqual(error.exception.code, 2)
