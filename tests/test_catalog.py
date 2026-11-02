"""Catalog contract tests: validation, loading, writing, atomicity."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.catalog import (
    BINARY_MAGIC,
    BINARY_VERSION_V2,
    FLAG_HAS_JET,
    FLAG_HAS_PARENT,
    SCALE_CODES,
    encode_binary_catalog,
    encode_binary_catalog_v2,
    load_catalog,
    read_binary_catalog,
    read_binary_catalog_v2,
    validate_catalog,
    write_binary_catalog,
    write_binary_catalog_v2,
    write_catalog,
)
import data.catalog as catalog_module


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


class BinaryCatalogTests(unittest.TestCase):
    def test_write_read_roundtrip_size(self):
        objects = [body(id=f"o{i}", parent=None if i == 0 else "o0") for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.bin"
            write_binary_catalog(path, objects)
            self.assertTrue(path.exists())
            parsed = read_binary_catalog(path)
            self.assertEqual(parsed["count"], 5)
            self.assertEqual(parsed["version"], 1)
            # magic check
            with open(path, "rb") as f:
                self.assertEqual(f.read(4), BINARY_MAGIC)
            # size ~ 26 bytes/object + header
            self.assertEqual(path.stat().st_size, 20 + 5 * 26)

    def test_large_catalog_size_approx_30mb(self):
        objects = [body(id=f"o{i}") for i in range(100000)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.bin"
            write_binary_catalog(path, objects)
            size_mb = path.stat().st_size / (1024 * 1024)
            self.assertLess(size_mb, 3.0)  # 100k -> ~2.5MB, linear to ~25MB for 1M
            self.assertGreater(size_mb, 2.0)

    def test_invalid_magic_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.bin"
            path.write_bytes(b"NOPE" + b"\x00" * 16)
            with self.assertRaises(ValueError):
                read_binary_catalog(path)

    def test_parent_flags_and_indices(self):
        objects = [body(id="a"), body(id="b", parent="a")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "parents.bin"
            write_binary_catalog(path, objects)
            parsed = read_binary_catalog(path)
        self.assertEqual(parsed["flags"][0], 0)
        self.assertEqual(parsed["parent_indices"][0], -1)
        self.assertEqual(parsed["flags"][1], FLAG_HAS_PARENT)
        self.assertEqual(parsed["parent_indices"][1], 0)

    def test_encode_allows_filtered_subset_with_dangling_parent(self):
        # `/api/objects?kind=` hands a subset to the encoder: the child's parent
        # is outside the subset. `write_binary_catalog` validates and must keep
        # rejecting this, but `encode_binary_catalog` must not.
        objects = [body(id="child", parent="missing")]
        with self.assertRaisesRegex(ValueError, "unknown parent"):
            with tempfile.TemporaryDirectory() as tmp:
                write_binary_catalog(Path(tmp) / "full.bin", objects)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subset.bin"
            path.write_bytes(encode_binary_catalog(objects))
            parsed = read_binary_catalog(path)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["flags"][0], FLAG_HAS_PARENT)
        self.assertEqual(parsed["parent_indices"][0], -1)

    def test_read_binary_catalog_uses_environment_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "objects.bin"
            write_binary_catalog(path, [body()])
            with patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": str(path)}):
                parsed = read_binary_catalog()
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["version"], 1)

    def test_solar_position_is_heliocentric_au_on_x(self):
        # Every solar body used to be placed at ~4.35 ly from the Sun; positions
        # must follow the object's own scale instead.
        objects = [body(id="earth", scale="solar", au=1.0, distance=1.0)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solar.bin"
            write_binary_catalog(path, objects)
            parsed = read_binary_catalog(path)
        self.assertAlmostEqual(parsed["positions"][0], 1.0, places=5)
        self.assertAlmostEqual(parsed["positions"][1], 0.0, places=5)
        self.assertAlmostEqual(parsed["positions"][2], 0.0, places=5)

class BinaryCatalogV2Tests(unittest.TestCase):
    def test_v2_roundtrip_strings_scales_and_parents(self):
        objects = [
            body(id="sun", name="Солнце", latin="Sol", scale="solar",
                 radius_km=696340, has_jet=False),
            body(id="star_a", name="Звезда A", latin="Star A", kind="star",
                 scale="local", parent=None, radius=1.5, radius_km=700000,
                 radius_earth=1.1, temperature_k=5800),
            body(id="planet_a", name="Планета A", latin="Planet A",
                 kind="exoplanet", scale="local", parent="star_a", au=0.5,
                 period_days=42.0, radius=0.2),
            body(id="bh", name="Дыра", latin="Hole", kind="black_hole",
                 scale="galaxy", parent=None, has_jet=True),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.v2.bin"
            write_binary_catalog_v2(path, objects)
            parsed = read_binary_catalog_v2(path)
            # The dispatch reader must recognise v2 as well.
            self.assertEqual(read_binary_catalog(path)["version"], BINARY_VERSION_V2)

        self.assertEqual(parsed["version"], BINARY_VERSION_V2)
        self.assertEqual(parsed["count"], 4)
        self.assertEqual(parsed["ids"], ["sun", "star_a", "planet_a", "bh"])
        self.assertEqual(parsed["names"], ["Солнце", "Звезда A", "Планета A", "Дыра"])
        self.assertEqual(parsed["latins"], ["Sol", "Star A", "Planet A", "Hole"])
        self.assertEqual(list(parsed["scales"]), [
            SCALE_CODES["solar"], SCALE_CODES["local"],
            SCALE_CODES["local"], SCALE_CODES["galaxy"],
        ])
        self.assertEqual(parsed["parents"], [None, None, "star_a", None])
        self.assertEqual(parsed["flags"][1], 0)
        self.assertEqual(parsed["flags"][2], FLAG_HAS_PARENT)
        self.assertEqual(parsed["flags"][3], FLAG_HAS_JET)
        self.assertAlmostEqual(parsed["radius_km"][0], 696340.0, places=1)
        self.assertAlmostEqual(parsed["radius_earth"][1], 1.1, places=6)
        self.assertAlmostEqual(parsed["au"][2], 0.5, places=6)
        self.assertAlmostEqual(parsed["period_days"][2], 42.0, places=6)

    def test_v2_header_offsets_are_aligned_and_monotonic(self):
        objects = [body(id=f"o{i}", parent=None if i == 0 else "o0") for i in range(7)]
        data = encode_binary_catalog_v2(objects)
        import struct
        magic, version, count, header_size, section_count = struct.unpack_from(
            "<4sIIII", data, 0
        )
        self.assertEqual(magic, BINARY_MAGIC)
        self.assertEqual(version, BINARY_VERSION_V2)
        self.assertEqual(count, 7)
        self.assertEqual(section_count, len(catalog_module.BINARY_V2_SECTIONS))
        offsets = struct.unpack_from(f"<{section_count}Q", data, 20)
        self.assertEqual(offsets[0], header_size)
        self.assertEqual(list(offsets), sorted(offsets))
        for offset in offsets[:-1]:
            self.assertEqual(offset % 4, 0)

    def test_v2_matches_v1_core_arrays(self):
        objects = [
            body(id="a", kind="star", scale="local", radius=1.0, color="#aabbcc"),
            body(id="b", kind="exoplanet", scale="local", parent="a", radius=0.2),
            body(id="c", kind="galaxy", scale="galaxy", radius=3.0, color="#010203"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            v1_path = Path(tmp) / "v1.bin"
            v2_path = Path(tmp) / "v2.bin"
            v1_path.write_bytes(encode_binary_catalog(objects))
            v2_path.write_bytes(encode_binary_catalog_v2(objects))
            v1 = catalog_module.read_binary_catalog(v1_path)
            v2 = catalog_module.read_binary_catalog(v2_path)
        self.assertEqual(list(v1["positions"]), list(v2["positions"]))
        self.assertEqual(list(v1["sizes"]), list(v2["sizes"]))
        self.assertEqual(list(v1["colors"]), list(v2["colors"]))
        self.assertEqual(list(v1["kinds"]), list(v2["kinds"]))
        self.assertEqual(list(v1["flags"]), list(v2["flags"]))
        self.assertEqual(list(v1["parent_indices"]), list(v2["parent_indices"]))

    def test_v2_is_equivalent_to_json_seed_catalog(self):
        # Positions, kind, color, scale, parent, size and physical radii must
        # survive the JSON -> v2 -> typed-array roundtrip. This is the contract
        # the frontend relies on when it stops reading the JSON catalog.
        seed = load_catalog(ROOT / "data" / "catalog_seed.json")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seed.v2.bin"
            write_binary_catalog_v2(path, seed)
            parsed = read_binary_catalog_v2(path)

        self.assertEqual(parsed["count"], len(seed))
        for index, item in enumerate(seed):
            x, y, z = catalog_module._render_position(item)
            # Galaxy positions are thousands of units; float32 keeps ~5
            # significant digits, so compare with a relative tolerance.
            for axis, expected in enumerate((x, y, z)):
                actual = parsed["positions"][index * 3 + axis]
                self.assertAlmostEqual(
                    actual, expected, delta=max(abs(expected) * 1e-5, 1e-3)
                )
            self.assertEqual(parsed["ids"][index], item["id"])
            self.assertEqual(parsed["names"][index], item["name"])
            self.assertEqual(parsed["latins"][index], item.get("latin") or "")
            self.assertEqual(
                parsed["kinds"][index], catalog_module.KIND_CODES[item["kind"]]
            )
            self.assertEqual(
                parsed["scales"][index], SCALE_CODES[item["scale"]]
            )
            self.assertEqual(
                parsed["colors"][index],
                catalog_module._color_to_uint32(item.get("color")),
            )
            self.assertEqual(parsed["parents"][index], item.get("parent"))
            self.assertAlmostEqual(
                parsed["sizes"][index], item.get("radius") or 0.0, places=4
            )
            self.assertAlmostEqual(
                parsed["radius_km"][index], item.get("radius_km") or 0.0, places=1
            )
            self.assertAlmostEqual(
                parsed["radius_earth"][index], item.get("radius_earth") or 0.0, places=4
            )

    def test_v2_filtered_subset_keeps_dangling_parent(self):
        objects = [body(id="child", parent="missing")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subset.v2.bin"
            path.write_bytes(encode_binary_catalog_v2(objects))
            parsed = read_binary_catalog_v2(path)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["flags"][0], FLAG_HAS_PARENT)
        self.assertEqual(parsed["parent_indices"][0], -1)
        self.assertIsNone(parsed["parents"][0])

    def test_v2_rejects_truncated_or_corrupt_input(self):
        objects = [body()]
        data = encode_binary_catalog_v2(objects)
        with tempfile.TemporaryDirectory() as tmp:
            truncated = Path(tmp) / "truncated.v2.bin"
            truncated.write_bytes(data[:-3])
            with self.assertRaises(ValueError):
                read_binary_catalog_v2(truncated)

            bad_version = Path(tmp) / "bad.v2.bin"
            bad_version.write_bytes(data[:4] + (99).to_bytes(4, "little") + data[8:])
            with self.assertRaises(ValueError):
                read_binary_catalog_v2(bad_version)


if __name__ == "__main__":
    unittest.main(verbosity=2)
