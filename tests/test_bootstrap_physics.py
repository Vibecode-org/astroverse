"""The SQLite startup migration preserves cards and physical uncertainty."""

from collections import Counter
import json
from pathlib import Path
import tempfile
import unittest

from data.bootstrap_catalog import bootstrap_database, build_bootstrap
from data.catalog import (
    encode_binary_catalog, encode_binary_catalog_v2, load_catalog,
)
from data.coordinates import coordinate_contract, snapshot_coordinates
from data.ephemeris import Ephemeris, contract
from data.runtime_catalog import DiskCatalog
from data.source_registry import REGISTRY


class BootstrapPhysicsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.seed = Path(__file__).resolve().parents[1] / "data/catalog_seed.json"
        cls.items = load_catalog(cls.seed)
        cls.bootstrap = Path(cls.temporary.name) / "bootstrap.sqlite"
        build_bootstrap(cls.seed, cls.bootstrap)
        cls.runtime = Path(cls.temporary.name) / "runtime.sqlite"
        bootstrap_database(cls.runtime, bootstrap=cls.bootstrap)

    def test_complete_cards_order_sources_and_nulls_survive_cold_start(self):
        with DiskCatalog(self.runtime).snapshot() as snapshot:
            actual = list(snapshot.select())
            self.assertEqual(snapshot.metadata["coordinates"], coordinate_contract())
        # Equality covers parent graph, all unknown fields, Cyrillic text and
        # source attribution, rather than only selected known measurements.
        self.assertEqual(len(actual), 3471)
        self.assertEqual(actual, self.items)
        self.assertEqual(Counter(item.get("source") for item in actual),
                         Counter(item.get("source") for item in self.items))
        self.assertEqual(Counter(snapshot_coordinates(item)["status"] for item in actual),
                         {"unknown": 2019, "unverified": 1452})
        for item in actual:
            coordinates = snapshot_coordinates(item)
            for field in ("reference_system", "origin", "source_epoch",
                          "evaluated_at", "time_scale", "accuracy",
                          "simulation_position"):
                self.assertIsNone(coordinates[field], (item["id"], field))
            if item["scale"] == "solar" or item.get("parent"):
                self.assertIsNone(coordinates["position"], item["id"])

    def test_legacy_representations_preserve_seed_bytes(self):
        with DiskCatalog(self.runtime).snapshot() as snapshot:
            for version, encoder in (("v1", encode_binary_catalog),
                                     ("v2", encode_binary_catalog_v2)):
                with self.subTest(version=version):
                    self.assertEqual(b"".join(snapshot.binary(version)),
                                     encoder(self.items))

    def test_missing_measurements_stay_null_and_measured_zero_stays_zero(self):
        rows = [
            dict(id="zero", name="Measured zero", kind="star", scale="local",
                 ra=0, dec=0, distance_ly=0, source="unverified snapshot",
                 source_epoch=None, reference_system=None, accuracy=None),
            dict(id="unknown", name="Unknown distance", kind="star", scale="local",
                 ra=0, dec=0, distance_ly=None, radius_km=None,
                 mass_sun=None, source=None),
            dict(id="child", name="Host direction only", kind="exoplanet", scale="local",
                 parent="zero", ra=0, dec=0, distance_ly=10, source="NASA"),
        ]
        source = Path(self.temporary.name) / "unknowns.json"
        target = Path(self.temporary.name) / "unknowns.sqlite"
        source.write_text(json.dumps(rows), encoding="utf-8")
        build_bootstrap(source, target)
        with DiskCatalog(target).snapshot() as snapshot:
            self.assertEqual(list(snapshot.select()), rows)
            zero = snapshot_coordinates(snapshot.object("zero"))
            unknown = snapshot_coordinates(snapshot.object("unknown"))
            child = snapshot_coordinates(snapshot.object("child"))
        self.assertEqual(zero["position"], [0, 0, 0])
        self.assertEqual(zero["status"], "unverified")
        for coordinates in (unknown, child):
            self.assertIsNone(coordinates["position"])
            self.assertEqual(coordinates["status"], "unknown")

    def test_catalog_jpl_labels_do_not_expand_verified_ephemeris_membership(self):
        expected = {"sun": 10, "earth": 399, "moon": 301,
                    "mercury": 199, "venus": 299}
        self.assertEqual(dict(REGISTRY.targets), expected)
        with DiskCatalog(self.runtime).snapshot() as snapshot:
            # This known catalog command must not opt Mars into the physical
            # scene or replace a body center with any kernel barycenter.
            self.assertEqual(snapshot.object("mars")["jpl_command"], "499")
        engine = Ephemeris()
        self.addCleanup(engine.close)
        frame = engine.evaluate(jd_tdb=2451545)
        self.assertEqual({item["id"]: item["target"] for item in frame["objects"]}, expected)
        self.assertIsNone(contract()["accuracy"])
        self.assertIsNone(contract()["source_epoch"])
        unknown = engine.evaluate(jd_tdb=2451545, ids=["mars"])["objects"][0]
        self.assertEqual(unknown["status"], "unknown")
        self.assertIsNone(unknown["position"])


if __name__ == "__main__":
    unittest.main()
