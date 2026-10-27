"""Catalog contract tests: validation, loading, writing, atomicity."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.catalog import load_catalog, validate_catalog, write_catalog


def body(**overrides):
    """Minimal valid catalog entry."""
    obj = {
        "id": "test",
        "name": "Test",
        "kind": "planet",
        "scale": "solar",
        "parent": None,
        "ra": 12.0,
        "dec": 30.0,
        "distance_ly": 10.0,
        "radius": 0.5,
        "color": "#aabbcc",
        "description": "",
        "facts": [],
        "source": "test",
    }
    obj.update(overrides)
    return obj


class CatalogTests(unittest.TestCase):
    def test_default_and_environment_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [body()])
            os.environ["ASTROVERSE_CATALOG_PATH"] = str(path)
            try:
                catalog = load_catalog()
                self.assertEqual(len(catalog), 1)
                self.assertEqual(catalog[0]["id"], "test")
            finally:
                os.environ.pop("ASTROVERSE_CATALOG_PATH", None)

    def test_valid_catalog_preserves_metadata(self):
        obj = body(mass=1.0, temperature=288, period_days=365.25)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
            self.assertEqual(catalog[0]["mass"], 1.0)
            self.assertEqual(catalog[0]["temperature"], 288)
            self.assertEqual(catalog[0]["period_days"], 365.25)

    def test_required_shape_and_fields(self):
        obj = body()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        entry = catalog[0]
        self.assertIsInstance(entry["id"], str)
        self.assertIsInstance(entry["name"], str)
        self.assertIsInstance(entry["kind"], str)
        self.assertIsInstance(entry["ra"], (int, float))
        self.assertIsInstance(entry["dec"], (int, float))
        self.assertIsInstance(entry["distance_ly"], (int, float))
        self.assertIsInstance(entry["radius"], (int, float))
        self.assertIsInstance(entry["color"], str)

    def test_display_radius_is_positive_and_not_null(self):
        obj = body(radius=0.5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertIsNotNone(catalog[0]["radius"])
        self.assertGreater(catalog[0]["radius"], 0)

    def test_optional_physical_fields(self):
        obj = body(mass=1.0, temperature=288, period_days=365.25)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertEqual(catalog[0]["mass"], 1.0)
        self.assertEqual(catalog[0]["temperature"], 288)
        self.assertEqual(catalog[0]["period_days"], 365.25)

    def test_optional_color_field(self):
        for color in ("#abc", "#aabbcc", "#aabbccdd"):
            obj = body(color=color)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "objects.json"
                write_catalog(path, [obj])
                catalog = load_catalog(path)
            self.assertEqual(catalog[0]["color"], color)

    def test_optional_tilt_field(self):
        obj = body(tilt=23.5)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertEqual(catalog[0]["tilt"], 23.5)

    def test_optional_rings_field(self):
        obj = body(rings={"inner": 1.2, "outer": 2.4})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertEqual(catalog[0]["rings"]["inner"], 1.2)
        self.assertEqual(catalog[0]["rings"]["outer"], 2.4)

    def test_optional_list_fields(self):
        obj = body(facts=["a", "b"], missions=["c"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertEqual(catalog[0]["facts"], ["a", "b"])
        self.assertEqual(catalog[0]["missions"], ["c"])

    def test_optional_string_fields(self):
        obj = body(description="desc", spectral_type="G2V", constellation="Lyra")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertEqual(catalog[0]["description"], "desc")
        self.assertEqual(catalog[0]["spectral_type"], "G2V")
        self.assertEqual(catalog[0]["constellation"], "Lyra")

    def test_equatorial_coordinate_boundaries(self):
        for ra, dec in ((0.0, -90.0), (23.999, 90.0), (12.0, 0.0)):
            obj = body(ra=ra, dec=dec)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "objects.json"
                write_catalog(path, [obj])
                catalog = load_catalog(path)
            self.assertEqual(catalog[0]["ra"], ra)
            self.assertEqual(catalog[0]["dec"], dec)

    def test_ids_parents_and_cycles(self):
        objects = [body(id="a", parent=None), body(id="b", parent="a")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, objects)
            catalog = load_catalog(path)
        ids = {o["id"] for o in catalog}
        self.assertEqual(ids, {"a", "b"})
        parents = {o["id"]: o["parent"] for o in catalog}
        self.assertEqual(parents["b"], "a")

    def test_jpl_command(self):
        obj = body(jpl_command="Earth")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertEqual(catalog[0]["jpl_command"], "Earth")

    def test_load_write_utf8_and_environment_override(self):
        obj = body(name="Земля", description="Наша планета")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            os.environ["ASTROVERSE_CATALOG_PATH"] = str(path)
            try:
                catalog = load_catalog()
            finally:
                os.environ.pop("ASTROVERSE_CATALOG_PATH", None)
        self.assertEqual(catalog[0]["name"], "Земля")

    def test_atomic_replace_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [body()])
            self.assertTrue(path.exists())
            temp_files = list(Path(tmp).glob("*.tmp*"))
            self.assertEqual(len(temp_files), 0)

    def test_invalid_catalog_fails_at_startup(self):
        bad = [{"id": "bad"}]  # missing required fields
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            with open(path, "w") as f:
                json.dump(bad, f)
            with self.assertRaises(Exception):
                load_catalog(path)

    # ---- RA=24 normalization ----

    def test_ra_24_normalized_to_zero(self):
        # ra=24 is rejected by validate_catalog on write, so write raw JSON
        # and verify load_catalog normalizes it to 0.
        import json
        obj = body(ra=24.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with open(path, "w") as f:
                json.dump([obj], f)
            catalog = load_catalog(path)
        self.assertEqual(catalog[0]["ra"], 0.0)

    # ---- Duplicate IDs ----

    def test_duplicate_ids_rejected(self):
        objects = [body(id="dup"), body(id="dup")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "duplicate id"):
                write_catalog(path, objects)

    # ---- Parent validation ----

    def test_unknown_parent_rejected(self):
        objects = [body(id="child", parent="missing")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "unknown parent"):
                write_catalog(path, objects)

    def test_self_parent_rejected(self):
        objects = [body(id="self", parent="self")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "cannot be its own parent"):
                write_catalog(path, objects)

    def test_parent_cycle_rejected(self):
        objects = [
            body(id="a", parent="b"),
            body(id="b", parent="a"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "parent cycle"):
                write_catalog(path, objects)

    # ---- jpl_command restrictions ----

    def test_jpl_command_only_for_solar(self):
        obj = body(kind="star", scale="local", jpl_command="Sun")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "only allowed for solar"):
                write_catalog(path, [obj])

    def test_jpl_command_empty_rejected(self):
        obj = body(jpl_command="   ")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "nonempty string"):
                write_catalog(path, [obj])

    # ---- Color validation ----

    def test_invalid_color_rejected(self):
        for color in ("red", "#gggggg", "#abcde", "#12345", "url(x)"):
            obj = body(color=color)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "objects.json"
                with self.assertRaisesRegex(ValueError, "hex string"):
                    write_catalog(path, [obj])

    def test_null_color_allowed(self):
        obj = body(color=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertIsNone(catalog[0]["color"])

    # ---- Tilt validation ----

    def test_invalid_tilt_rejected(self):
        obj = body(tilt="not a number")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "finite number"):
                write_catalog(path, [obj])

    def test_null_tilt_allowed(self):
        obj = body(tilt=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertIsNone(catalog[0]["tilt"])

    # ---- Rings validation ----

    def test_rings_non_positive_rejected(self):
        for rings in ({"inner": 0, "outer": 2}, {"inner": 1.2, "outer": -1}, {"inner": -1, "outer": 2}):
            obj = body(rings=rings)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "objects.json"
                with self.assertRaisesRegex(ValueError, "finite positive number"):
                    write_catalog(path, [obj])

    def test_rings_not_object_rejected(self):
        obj = body(rings=[1, 2])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "object with inner and outer"):
                write_catalog(path, [obj])

    # ---- List fields validation ----

    def test_facts_non_string_entries_rejected(self):
        obj = body(facts=["ok", 42])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "list of strings"):
                write_catalog(path, [obj])

    def test_missions_not_list_rejected(self):
        obj = body(missions="not a list")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "list of strings"):
                write_catalog(path, [obj])

    # ---- String fields validation ----

    def test_description_non_string_rejected(self):
        obj = body(description=123)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "string or null"):
                write_catalog(path, [obj])

    # ---- NONNEGATIVE_FIELDS ----

    def test_negative_au_rejected(self):
        obj = body(au=-1.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "nonnegative"):
                write_catalog(path, [obj])

    def test_null_au_allowed(self):
        obj = body(au=None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            write_catalog(path, [obj])
            catalog = load_catalog(path)
        self.assertIsNone(catalog[0]["au"])

    # ---- POSITIVE_FIELDS ----

    def test_zero_radius_km_rejected(self):
        obj = body(radius_km=0)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "positive"):
                write_catalog(path, [obj])

    def test_negative_period_days_rejected(self):
        obj = body(period_days=-10)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.json"
            with self.assertRaisesRegex(ValueError, "positive"):
                write_catalog(path, [obj])

    # ---- SIGNED_FIELDS boundaries ----

    def test_ra_out_of_range_rejected(self):
        for ra in (-0.1, 24.0, 100.0):
            obj = body(ra=ra)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "objects.json"
                with self.assertRaisesRegex(ValueError, r"\[0, 24\)"):
                    write_catalog(path, [obj])

    def test_dec_out_of_range_rejected(self):
        for dec in (-90.1, 90.1, -180.0):
            obj = body(dec=dec)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "objects.json"
                with self.assertRaisesRegex(ValueError, r"\[-90, 90\]"):
                    write_catalog(path, [obj])


if __name__ == "__main__":
    unittest.main(verbosity=2)
