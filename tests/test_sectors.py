"""Physical-space partitioning, parent closure and disk artifact integrity."""

import copy
import math
from pathlib import Path
import tempfile
import unittest

from data.catalog import encode_binary_catalog_v2, load_catalog, validate_catalog
from data.sectors import SectorIndex, build_sector_index, physical_position


def star(oid, distance, ra=0, **extra):
    return dict(id=oid, name=oid, kind="star", scale="local", ra=ra,
                dec=0, distance_ly=distance, **extra)


class SectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sectors.sqlite"

    def build(self, items, **options):
        build_sector_index(self.path, items, **options)
        return SectorIndex(self.path)

    def test_physical_positions_are_linear_and_unknown_is_not_invented(self):
        self.assertEqual(physical_position(star("a", 80)), ("equatorial", 80, 0, 0))
        point = physical_position(star("b", 80, ra=6))
        self.assertAlmostEqual(point[1], 0)
        self.assertEqual(point[3], 80)
        self.assertIsNone(physical_position(star("unknown", None)))
        self.assertIsNone(physical_position(dict(gx=100, gy=2, gz=3, distance_ly=80)))
        self.assertEqual(physical_position(dict(distance_ly=0, ra=0, dec=0)),
                         ("equatorial", 0, 0, 0))
        galactic = physical_position(dict(distance_ly=80, galactic_l=0, galactic_b=90))
        self.assertEqual(galactic[0], "galactic")
        self.assertAlmostEqual(galactic[2], 80)

    def test_children_stay_with_root_even_with_other_coordinates_or_input_order(self):
        items = [
            dict(id="moon", name="Moon", kind="moon", scale="local", parent="planet"),
            dict(id="planet", name="Planet", kind="exoplanet", scale="local",
                 parent="host", ra=12, dec=0, distance_ly=10000),
            star("other", 100), star("host", 10),
        ]
        index = self.build(items, max_objects=1)
        sector = index.locate("host")
        self.assertEqual(index.locate("planet"), sector)
        self.assertEqual(index.locate("moon"), sector)
        self.assertNotEqual(index.locate("other"), sector)
        objects = index.objects(sector)
        validate_catalog(objects)
        self.assertEqual({o["id"] for o in objects}, {"host", "planet", "moon"})
        self.assertTrue(encode_binary_catalog_v2(objects).startswith(b"ASTV"))
        self.assertIsNone(index.locate("absent"))
        with self.assertRaises(KeyError):
            index.objects("absent")

    def test_octree_splits_dense_cells_and_bounds_contain_roots(self):
        items = [star("a", 1), star("b", 3), star("c", 20), star("d", 30),
                 star("negative", 10, ra=12)]
        index = self.build(items, max_objects=1)
        leaves = index.sectors()
        self.assertEqual(len(leaves), 5)
        self.assertTrue(any(row["depth"] > 0 for row in leaves))
        for obj in items:
            leaf = next(row for row in leaves if row["id"] == index.locate(obj["id"]))
            for axis, value in zip("xyz", physical_position(obj)[1:]):
                self.assertLessEqual(leaf[f"min_{axis}"], value)
                self.assertLessEqual(value, leaf[f"max_{axis}"])
        self.assertTrue(index.locate("negative").startswith("local:equatorial:-1:"))

    def test_coincident_systems_terminate_and_preserve_all_objects(self):
        index = self.build([star("a", 1), star("b", 1)], max_objects=1, max_depth=4)
        leaves = index.sectors()
        self.assertEqual(len(leaves), 1)
        self.assertEqual(leaves[0]["depth"], 4)
        self.assertEqual(leaves[0]["object_count"], 2)

    def test_unknown_solar_and_frames_are_separate(self):
        items = [star("unknown", None), star("known", 10),
                 dict(id="sun", name="Sun", kind="star", scale="solar"),
                 dict(id="nebula", name="Nebula", kind="nebula", scale="galaxy",
                      distance_ly=10, galactic_l=0, galactic_b=0)]
        index = self.build(items)
        self.assertEqual(len(index.sectors()), 4)
        self.assertEqual([s["object_count"] for s in index.nearby(
            "local", "equatorial", (10, 0, 0), 0)], [1])
        self.assertEqual(index.nearby("local", "galactic", (10, 0, 0), 0), [])
        self.assertEqual(len(index.nearby("galaxy", "galactic", (10, 0, 0), 0)), 1)

    def test_nearby_sphere_intersection_rejects_box_corner_false_positive(self):
        index = self.build([star("a", 10)])
        self.assertEqual(len(index.nearby("local", "equatorial", (33, 0, 0), 1)), 1)
        self.assertEqual(index.nearby("local", "equatorial", (33, 33, 33), 1), [])
        self.assertEqual(index.nearby("local", "equatorial", (1000, 0, 0), 1), [])
        for center, radius in [((0, 0), 1), ((math.nan, 0, 0), 1), ((0, 0, 0), -1),
                               ((0, 0, 0), math.inf), ((True, 0, 0), 1)]:
            with self.assertRaises(ValueError):
                index.nearby("local", "equatorial", center, radius)

    def test_rebuild_order_determinism_and_sector_local_revisions(self):
        items = [star("near", 10), star("far", 100)]
        index = self.build(items)
        before = index.sectors()
        self.build(list(reversed(items)))
        self.assertEqual(SectorIndex(self.path).sectors(), before)
        changed = copy.deepcopy(items)
        changed[0]["name"] = "Changed"
        after = self.build(changed).sectors()
        previous = {row["id"]: row["revision"] for row in before}
        current = {row["id"]: row["revision"] for row in after}
        self.assertNotEqual(previous[index.locate("near")], current[index.locate("near")])
        self.assertEqual(previous[index.locate("far")], current[index.locate("far")])

    def test_invalid_input_leaves_previous_artifact_intact_and_no_temporary_file(self):
        self.build([star("a", 10)])
        previous = self.path.read_bytes()
        for invalid in [[star("a", 10), star("a", 20)],
                        [star("orphan", 10, parent="absent")],
                        [star("cycle", 10, parent="cycle")],
                        [star("bad", float("nan"))],
                        [star("a", 10), dict(id="b", name="b", kind="moon",
                                             scale="solar", parent="a")]]:
            with self.assertRaises(ValueError):
                self.build(invalid)
            self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], [self.path.name])

    def test_write_failure_cleans_temporary_database_and_preserves_previous_index(self):
        self.build([star("a", 10)])
        previous = self.path.read_bytes()
        # Unknown metadata is preserved by the catalog contract, but this value
        # cannot be serialized. Fail after creating the temporary database.
        with self.assertRaises(TypeError):
            self.build([star("a", 10, extra={object()})])
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], [self.path.name])

    def test_invalid_configuration_and_empty_catalog(self):
        for config in [dict(cell_size_ly=0), dict(cell_size_ly=math.inf),
                       dict(max_objects=0), dict(max_depth=-1), dict(max_depth=33)]:
            with self.assertRaises(ValueError):
                self.build([], **config)
        index = self.build([])
        self.assertEqual(index.sectors(), [])
        self.assertEqual(index.metadata["object_count"], 0)

    def test_real_seed_roundtrip_has_no_lost_or_duplicated_objects(self):
        items = load_catalog(Path(__file__).resolve().parents[1] / "data/catalog_seed.json")
        index = self.build(items)
        restored = [obj for leaf in index.sectors() for obj in index.objects(leaf["id"])]
        self.assertEqual(sorted(restored, key=lambda o: o["id"]),
                         sorted(items, key=lambda o: o["id"]))
        for leaf in index.sectors():
            validate_catalog(index.objects(leaf["id"]))
        self.assertEqual(index.metadata["object_count"], 3471)


if __name__ == "__main__":
    unittest.main()
