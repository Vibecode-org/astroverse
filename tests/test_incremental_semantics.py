"""Patch results match a full build across graph and snapshot transitions."""

from contextlib import closing
import copy
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.coordinates import coordinate_contract, snapshot_coordinates
from data.incremental_catalog import publish_changes
from data.runtime_catalog import DiskCatalog
from data.sectors import SectorIndex
from data.streaming_catalog import build_streaming_index


def root(oid, distance=1, **fields):
    return dict(id=oid, name=oid, kind="star", scale="local", ra=0,
                dec=0, distance_ly=distance, **fields)


def child(oid, parent, **fields):
    return dict(id=oid, name=oid, kind="exoplanet", scale="local",
                parent=parent, **fields)


class IncrementalSemanticTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "published.sqlite"
        self.reference = Path(self.temporary.name) / "reference.sqlite"

    def build(self, items, **options):
        self.items = copy.deepcopy(items)
        self.options = options
        self.meta = build_streaming_index(self.path, None, objects=self.items,
                                          **options)

    def patch(self, *, upserts=(), deletes=()):
        # This oracle preserves existing input order and appends new IDs sorted,
        # independently of the incremental writer's graph/partition algorithm.
        pending = {item["id"]: copy.deepcopy(item) for item in upserts}
        removed = set(deletes)
        expected = [pending.pop(item["id"], item) for item in self.items
                    if item["id"] not in removed]
        expected.extend(pending[oid] for oid in sorted(pending))
        self.meta = publish_changes(
            self.path, expected_revision=self.meta["catalog_revision"],
            upserts=upserts, deletes=deletes)
        self.items = expected
        self.assert_full_build_parity()

    def assert_full_build_parity(self):
        reference_meta = build_streaming_index(
            self.reference, None, objects=self.items, **self.options)
        self.assertEqual(self.meta["catalog_revision"],
                         reference_meta["catalog_revision"])
        self.assertEqual(self.meta["object_count"], len(self.items))
        self.assertEqual(self.meta["coordinates"], coordinate_contract())
        actual = SectorIndex(self.path)
        reference = SectorIndex(self.reference)
        self.assertEqual(actual.sectors(), reference.sectors())
        for sector in reference.sectors():
            self.assertEqual(actual.objects(sector["id"]),
                             reference.objects(sector["id"]))
        with closing(sqlite3.connect(self.path)) as patched_db, \
                closing(sqlite3.connect(self.reference)) as full_db:
            # Persistent ordinals may have gaps after deletion. Their ordering,
            # cards, roots, search rows and binary parent indexes must agree.
            query = ("SELECT id,sector_id,root_id,payload,kind,scale,search_blob "
                     "FROM objects ORDER BY ordinal")
            self.assertEqual(patched_db.execute(query).fetchall(),
                             full_db.execute(query).fetchall())
            bounds = ("SELECT s.id,b.min_x,b.max_x,b.min_y,b.max_y,b.min_z,b.max_z "
                      "FROM sector_bounds b JOIN sectors s "
                      "ON s.rowid=b.sector_rowid ORDER BY s.id")
            self.assertEqual(patched_db.execute(bounds).fetchall(),
                             full_db.execute(bounds).fetchall())
            self.assertEqual(patched_db.execute("PRAGMA foreign_key_check").fetchall(), [])
        with DiskCatalog(self.path).snapshot() as patched, \
                DiskCatalog(self.reference).snapshot() as full:
            self.assertEqual(list(patched.select()), list(full.select()))
            for version in ("v1", "v2"):
                self.assertEqual(b"".join(patched.binary(version)),
                                 b"".join(full.binary(version)))

    def test_reparent_subtree_and_split_then_merge_base_cells(self):
        self.build([root("a", 1), child("planet", "a"),
                    child("moon", "planet"), root("b", 20), root("far", 100)],
                   max_objects=3)
        self.patch(upserts=[child("planet", "far")])
        index = SectorIndex(self.path)
        self.assertEqual(index.locate("planet"), index.locate("far"))
        self.assertEqual(index.locate("moon"), index.locate("far"))
        self.assertNotEqual(index.locate("a"), index.locate("far"))
        self.patch(upserts=[root("far", 10)])
        self.assertTrue(any(sector["depth"] > 0
                            for sector in SectorIndex(self.path).sectors()))
        self.patch(upserts=[root("far", 100)])
        near = [sector for sector in SectorIndex(self.path).sectors()
                if sector["id"].startswith("local:equatorial:0:0:0")]
        self.assertEqual(len(near), 1)
        self.assertEqual(near[0]["depth"], 0)
        # Detaching an internal node promotes its own coordinates to a root,
        # carrying its unchanged descendant into the new family.
        promoted = root("planet", 300)
        self.patch(upserts=[promoted])
        index = SectorIndex(self.path)
        self.assertEqual(index.locate("planet"), index.locate("moon"))
        self.assertNotEqual(index.locate("planet"), index.locate("far"))

    def test_child_coordinates_and_unknown_provenance_stay_unknown(self):
        self.build([root("host", 10, source="unverified-catalog"),
                    child("planet", "host", ra=12, dec=80, distance_ly=9000,
                          source="unverified-catalog")])
        before = SectorIndex(self.path).sectors()[0]
        changed = child("planet", "host", ra=6, dec=-80, distance_ly=None,
                        source="another-catalog", source_epoch=None,
                        accuracy=None, reference_system=None)
        self.patch(upserts=[changed])
        after = SectorIndex(self.path).sectors()[0]
        self.assertEqual(before["id"], after["id"])
        for field in ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z"):
            self.assertEqual(before[field], after[field])
        with DiskCatalog(self.path).snapshot() as snapshot:
            planet = snapshot_coordinates(snapshot.object("planet"))
            host = snapshot_coordinates(snapshot.object("host"))
        self.assertEqual(host["status"], "unverified")
        self.assertEqual(planet["status"], "unknown")
        self.assertIsNone(planet["position"])
        self.assertIsNone(planet["frame"])
        for coordinates in (host, planet):
            for field in ("reference_system", "origin", "source_epoch",
                          "evaluated_at", "time_scale", "accuracy",
                          "simulation_position"):
                self.assertIsNone(coordinates[field])

    def test_located_unlocated_frames_and_solar_transitions(self):
        self.build([root("host", 10), child("planet", "host"), root("other", 100)])
        self.patch(upserts=[root("host", None)])
        self.assertEqual(SectorIndex(self.path).locate("planet"), "local:unlocated")
        galactic = root("host", 10)
        galactic.update(ra=None, dec=None, galactic_l=90, galactic_b=0)
        self.patch(upserts=[galactic])
        self.assertTrue(SectorIndex(self.path).locate("host").startswith("local:galactic:"))
        # A complete RA/Dec pair takes precedence when both pairs are supplied.
        equatorial = dict(galactic, ra=0, dec=0)
        self.patch(upserts=[equatorial])
        self.assertTrue(SectorIndex(self.path).locate("host").startswith("local:equatorial:"))
        solar_root = dict(equatorial, scale="solar")
        solar_child = dict(child("planet", "host"), scale="solar")
        self.patch(upserts=[solar_root, solar_child])
        self.assertEqual(SectorIndex(self.path).locate("planet"), "solar:system")
        sector = next(s for s in SectorIndex(self.path).sectors() if s["id"] == "solar:system")
        self.assertTrue(all(sector[field] is None for field in
                            ("min_x", "min_y", "min_z", "max_x", "max_y", "max_z")))
        self.patch(upserts=[root("host", 10), child("planet", "host")])

    def test_final_graph_errors_are_atomic_and_final_graph_repair_is_valid(self):
        self.build([root("a", 1), child("b", "a"), child("c", "b"), root("d", 100)])
        invalid = [
            dict(upserts=[dict(root("a", 1), parent="c")]),
            dict(upserts=[dict(root("a", 1), parent="d"),
                          dict(root("d", 100), parent="a")]),
            dict(upserts=[child("b", "missing")]),
            dict(upserts=[dict(child("b", "a"), scale="solar")]),
            dict(upserts=[dict(root("a", 1), scale="solar")]),
            dict(deletes=["b"]),
            dict(upserts=[dict(child("b", "a"), parent="b")]),
        ]
        previous = self.path.read_bytes()
        for patch in invalid:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                publish_changes(self.path, expected_revision=self.meta["catalog_revision"], **patch)
            self.assertEqual(self.path.read_bytes(), previous)
        self.patch(upserts=[child("c", "d")], deletes=["b"])
        # Forward references introduced together are valid regardless of patch order.
        self.patch(upserts=[child("new-child", "new-root"), root("new-root", 300)])
        self.patch(upserts=[dict(child("c", "d"), parent=None)])
        self.assertEqual(SectorIndex(self.path).locate("c"), "local:unlocated")

    def test_delete_gaps_keep_order_binary_parent_indexes_and_hashes(self):
        self.build([root("discard", 1), child("moon", "planet"), root("host", 100),
                    child("planet", "host"), root("last", 200)], max_objects=2)
        self.patch(deletes=["discard", "last"],
                   upserts=[root("z-new", 400), root("a-new", 300)])
        self.patch(upserts=[dict(child("planet", "host"), name="Обновлённая планета",
                                 description="Distinct searchable phrase")])
        with DiskCatalog(self.path).snapshot() as snapshot:
            self.assertEqual([o["id"] for o in snapshot.select()],
                             ["moon", "host", "planet", "a-new", "z-new"])
            self.assertEqual([o["id"] for o in snapshot.select(q="обновлённая")], ["planet"])
        self.patch(deletes=["host", "planet", "moon"])

    def test_float_boundaries_negative_cells_and_coincident_roots(self):
        self.build([root("edge", math.nextafter(32, 0)), root("negative", 32),
                    root("same-a", 1), root("same-b", 1)],
                   max_objects=1, max_depth=4)
        self.patch(upserts=[root("edge", 32), dict(root("negative", 32), ra=18)])
        self.assertTrue(SectorIndex(self.path).locate("edge").startswith("local:equatorial:1:"))
        self.assertTrue(SectorIndex(self.path).locate("negative").startswith("local:equatorial:-1:"))
        self.patch(upserts=[root("edge", math.nextafter(32, math.inf))])


if __name__ == "__main__":
    unittest.main()
