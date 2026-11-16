"""Catalog recovery preserves scientific uncertainty and source provenance.

The backup contains the publication; the checksum-pinned ephemeris kernel and
the opted-in source registry remain versioned application assets.
"""

from collections import Counter
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest

from data.bootstrap_catalog import bootstrap_database, build_bootstrap
from data.catalog_backup import backup_database, restore_database
from data.coordinates import coordinate_contract, snapshot_coordinates
from data.ephemeris import Ephemeris, contract
from data.incremental_catalog import publish_changes
from data.runtime_catalog import DiskCatalog
from data.source_registry import REGISTRY
from data.streaming_catalog import build_streaming_index


class BackupPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.runtime = cls.root / "runtime.sqlite"
        bootstrap = cls.root / "bootstrap.sqlite"
        seed = Path(__file__).resolve().parents[1] / "data/catalog_seed.json"
        build_bootstrap(seed, bootstrap)
        bootstrap_database(cls.runtime, bootstrap=bootstrap)
        with DiskCatalog(cls.runtime).snapshot() as snapshot:
            cls.initial_revision = snapshot.metadata["catalog_revision"]
            sun = snapshot.object("sun")

        # Isolate preservation of arbitrary existing source metadata from HTTP
        # import behavior. This explicitly labelled fixture makes no scientific
        # claim about the bundled seed or its origin.
        cls.provenance = {
            "schema": "catalog-import/1", "source": "backup preservation fixture",
            "mode": "fixture", "semantic_revision": cls.initial_revision,
            "input": {"sha256": "a" * 64, "bytes": 1234},
            "source_epoch": None, "frame": None, "accuracy": None,
        }
        with sqlite3.connect(cls.runtime) as db:
            db.execute("INSERT INTO metadata VALUES ('import_manifest',?)",
                       (json.dumps(cls.provenance),))
        cls.original = cls.root / "restored-original.sqlite"
        backup_database(cls.runtime, cls.root / "original-backup")
        restore_database(cls.root / "original-backup", cls.original)

        cls.patched = publish_changes(
            cls.runtime, expected_revision=cls.initial_revision,
            upserts=[dict(sun, description="Backup recovery fixture annotation")])
        cls.bundle = cls.root / "patched-backup"
        cls.restored = cls.root / "restored-patched.sqlite"
        backup_database(cls.runtime, cls.bundle)
        restore_database(cls.bundle, cls.restored)

    def test_full_cards_coordinates_revisions_and_provenance_survive_restore(self):
        with DiskCatalog(self.original).snapshot() as snapshot:
            self.assertEqual(snapshot.metadata["import_manifest"], self.provenance)
            self.assertEqual(snapshot.metadata["catalog_revision"], self.initial_revision)
        with DiskCatalog(self.runtime).snapshot() as before, \
                DiskCatalog(self.restored).snapshot() as after:
            expected = list(before.select())
            actual = list(after.select())
            self.assertEqual(len(actual), 3471)
            # Covers every body field, parent relationship, order, source label,
            # missing value, measured zero and Unicode string.
            self.assertEqual(actual, expected)
            self.assertEqual(after.metadata, before.metadata)
            self.assertEqual(after.metadata["catalog_revision"], self.patched["catalog_revision"])
            self.assertEqual(after.metadata["parent_revision"], self.initial_revision)
            self.assertNotEqual(after.metadata["catalog_revision"], self.initial_revision)
            self.assertNotIn("import_manifest", after.metadata)
            self.assertEqual(after.metadata["previous_import_manifest"], self.provenance)
            self.assertEqual(after.metadata["coordinates"], coordinate_contract())
            self.assertEqual(list(after.sectors()), list(before.sectors()))
            for version in ("v1", "v2"):
                self.assertEqual(b"".join(after.binary(version)),
                                 b"".join(before.binary(version)))
        self.assertEqual(Counter(snapshot_coordinates(item)["status"] for item in actual),
                         {"unknown": 2019, "unverified": 1452})
        for item in actual:
            coordinates = snapshot_coordinates(item)
            for field in ("reference_system", "origin", "source_epoch", "evaluated_at",
                          "time_scale", "accuracy", "simulation_position"):
                self.assertIsNone(coordinates[field], (item["id"], field))
            if item["scale"] == "solar" or item.get("parent"):
                self.assertIsNone(coordinates["position"], item["id"])
        manifest = json.loads((self.bundle / "manifest.json").read_text())
        self.assertEqual(manifest["metadata"], self.patched)

    def test_measured_zero_and_unknown_child_centers_remain_distinct(self):
        rows = [
            dict(id="zero", name="Measured zero", kind="star", scale="local",
                 ra=0, dec=0, distance_ly=0, mass_sun=0, source="unverified snapshot",
                 source_epoch=None, reference_system=None, accuracy=None),
            dict(id="unknown", name="Unknown distance", kind="star", scale="local",
                 ra=0, dec=0, distance_ly=None, radius_km=None,
                 mass_sun=None, source=None),
            dict(id="child", name="Host direction only", kind="exoplanet", scale="local",
                 parent="zero", ra=0, dec=0, distance_ly=10, source="NASA"),
        ]
        source = self.root / "unknowns.sqlite"
        restored = self.root / "restored-unknowns.sqlite"
        bundle = self.root / "unknowns-backup"
        build_streaming_index(source, None, objects=iter(rows))
        backup_database(source, bundle)
        restore_database(bundle, restored)
        with DiskCatalog(restored).snapshot() as snapshot:
            self.assertEqual(list(snapshot.select()), rows)
            zero = snapshot_coordinates(snapshot.object("zero"))
            self.assertEqual(zero["position"], [0, 0, 0])
            self.assertEqual(zero["status"], "unverified")
            for oid in ("unknown", "child"):
                coordinates = snapshot_coordinates(snapshot.object(oid))
                self.assertIsNone(coordinates["position"])
                self.assertEqual(coordinates["status"], "unknown")

    def test_recovered_cards_keep_five_opted_in_centers_and_horizons_vectors(self):
        expected = {"sun": 10, "earth": 399, "moon": 301,
                    "mercury": 199, "venus": 299}
        self.assertEqual(dict(REGISTRY.targets), expected)
        with DiskCatalog(self.restored).snapshot() as snapshot:
            for oid in expected:
                self.assertIsNotNone(snapshot.object(oid))
            # A recovered catalog source label is not a verified model opt-in.
            self.assertEqual(snapshot.object("mars")["jpl_command"], "499")
        engine = Ephemeris()
        self.addCleanup(engine.close)
        fixture = json.loads((Path(__file__).parent / "fixtures/horizons_centers.json").read_text())
        self.assertEqual({body["id"]: body["target"] for body in fixture["samples"]}, expected)
        self.assertEqual((fixture["reference_system"], fixture["time_scale"], fixture["unit"]),
                         ("ICRF", "TDB", "km"))
        self.assertEqual(fixture["corrections"], "NONE")
        samples = 0
        for body in fixture["samples"]:
            self.assertEqual(len(body["rows"]), 20)
            for reference in body["rows"]:
                actual = engine.evaluate(jd_tdb=reference["jd_tdb"], ids=[body["id"]])["objects"][0]
                with self.subTest(id=body["id"], jd=reference["jd_tdb"]):
                    self.assertEqual(actual["target"], body["target"])
                    self.assertLess(math.dist(actual["position"], reference["position"]),
                                    fixture["tolerance_km"])
                samples += 1
        self.assertEqual(samples, 100)
        unknown = engine.evaluate(jd_tdb=2451545, ids=["mars"])["objects"][0]
        self.assertEqual(unknown["status"], "unknown")
        self.assertIsNone(unknown["position"])
        self.assertIsNone(contract()["accuracy"])
        self.assertIsNone(contract()["source_epoch"])


if __name__ == "__main__":
    unittest.main()
