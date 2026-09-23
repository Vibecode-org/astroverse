"""Run from the project root: python -m unittest discover -s tests -t . -v."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data import catalog


def body(object_id="test-body", /, **fields):
    return {"id": object_id, "name": "Тестовый мир", "kind": "planet", "scale": "solar", **fields}


@contextmanager
def isolated_app(items):
    # Exercise the real import-time loader without depending on checked-in seeds.
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "catalog.json"
        catalog.write_catalog(path, items)
        with mock.patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": str(path)}):
            spec = importlib.util.spec_from_file_location("astroverse_test_app", ROOT / "backend" / "app.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            yield module


class CatalogTests(unittest.TestCase):
    def test_default_and_environment_path(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(catalog.catalog_path(), ROOT / "data" / "objects.json")
            self.assertEqual(catalog.catalog_path(), catalog.DEFAULT_CATALOG_PATH)
        with mock.patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": "custom.json"}):
            self.assertEqual(catalog.catalog_path(), Path("custom.json"))

    def test_valid_catalog_preserves_metadata(self):
        items = [body("sun", kind="star", radius=1, ra=0, dec=-90),
                 body(parent="sun", jpl_command="399", facts=["fact"], extra={"a": 1})]
        self.assertIs(catalog.validate_catalog(items), items)
        self.assertEqual(items[1]["extra"], {"a": 1})
        self.assertEqual(catalog.validate_catalog([]), [])
        for kind in catalog.SUPPORTED_KINDS:
            for scale in catalog.SUPPORTED_SCALES:
                with self.subTest(kind=kind, scale=scale):
                    catalog.validate_catalog([body(kind=kind, scale=scale)])

    def test_required_shape_and_fields(self):
        for items in (None, {}, "[]", [None], [[]], [1]):
            with self.subTest(items=items), self.assertRaises(ValueError):
                catalog.validate_catalog(items)
        for field in ("id", "name", "kind", "scale"):
            item = body()
            del item[field]
            with self.subTest(missing=field), self.assertRaises(ValueError):
                catalog.validate_catalog([item])
            for value in (None, "", "  ", 2, True, [], {}):
                item = body()
                item[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    catalog.validate_catalog([item])
        for fields in ({"kind": "unknown"}, {"scale": "universe"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                catalog.validate_catalog([body(**fields)])

    def test_display_radius_is_positive_and_not_null(self):
        for value in (None, 0, -1, True, "1", float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                catalog.validate_catalog([body(radius=value)])
        catalog.validate_catalog([body(radius=0.01)])

    def test_optional_physical_fields(self):
        nonnegative = ("au", "distance", "distance_ly", "moon_distance", "mass_earth",
                       "mass_sun", "temperature_k", "gravity", "escape_velocity")
        positive = ("period_days", "radius_km", "radius_earth")
        signed = ("ra", "dec", "galactic_l", "galactic_b", "gx", "gy", "gz")
        for field in nonnegative + positive + signed:
            for value in (None, 1.5):
                with self.subTest(field=field, valid=value):
                    catalog.validate_catalog([body(**{field: value})])
            for value in (True, "1.5", [], float("nan"), float("inf"), float("-inf"), 10 ** 400):
                if field in ("gravity", "escape_velocity") and isinstance(value, str):
                    catalog.validate_catalog([body(**{field: value})])
                    continue
                with self.subTest(field=field, invalid=value), self.assertRaises(ValueError):
                    catalog.validate_catalog([body(**{field: value})])
        for field in nonnegative:
            catalog.validate_catalog([body(**{field: 0})])
            with self.subTest(field=field), self.assertRaises(ValueError):
                catalog.validate_catalog([body(**{field: -0.1})])
        for field in positive:
            for value in (0, -0.1):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    catalog.validate_catalog([body(**{field: value})])
        catalog.validate_catalog([body(gx=-1, gy=-1, gz=-1, galactic_b=-45)])

    def test_legacy_display_fields_and_ra_load_without_rewriting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            for value in ("274 м/с²", None):
                items = [body(gravity=value, escape_velocity="617.7 км/с", ra=24.0)]
                original = json.dumps(items, ensure_ascii=False)
                path.write_text(original, encoding="utf-8")
                loaded = catalog.load_catalog(path)
                self.assertEqual(loaded, [dict(items[0], ra=0.0)])
                self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_equatorial_coordinate_boundaries(self):
        for ra, dec in ((0, -90), (23.99999, 90), (12, 0)):
            catalog.validate_catalog([body(ra=ra, dec=dec)])
        for fields in ({"ra": -0.1}, {"ra": 24}, {"dec": -90.01}, {"dec": 90.01}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                catalog.validate_catalog([body(**fields)])

    def test_ids_parents_and_cycles(self):
        invalid = (
            [body(), body()],
            [body(parent="missing")],
            [body(parent="test-body")],
            [body(parent=[])],
            [body(parent="")],
            [body("a", parent="b"), body("b", parent="a")],
            [body("a", parent="b"), body("b", parent="c"), body("c", parent="a")],
        )
        for items in invalid:
            with self.subTest(items=items), self.assertRaises(ValueError):
                catalog.validate_catalog(items)
        catalog.validate_catalog([body("child", parent="parent"), body("parent", parent=None)])
        chain = [body(str(index), parent=str(index + 1)) for index in range(1500)]
        chain.append(body("1500"))
        catalog.validate_catalog(chain)

    def test_jpl_command(self):
        catalog.validate_catalog([body(jpl_command="DES=1;")])
        for value in (None, "", "  ", 399, False, []):
            with self.subTest(value=value), self.assertRaises(ValueError):
                catalog.validate_catalog([body(jpl_command=value)])
        for scale in ("local", "galaxy"):
            with self.subTest(scale=scale), self.assertRaises(ValueError):
                catalog.validate_catalog([body(scale=scale, jpl_command="399")])

    def test_load_write_utf8_and_environment_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            items = [body()]
            catalog.write_catalog(path, items)
            self.assertIn("Тестовый мир", path.read_text(encoding="utf-8"))
            self.assertEqual(catalog.load_catalog(path), items)
            with mock.patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": str(path)}):
                self.assertEqual(catalog.load_catalog(), items)
                self.assertEqual(catalog.load_catalog(path), items)
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                catalog.load_catalog(path)
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(json.JSONDecodeError):
                catalog.load_catalog(path)

    def test_atomic_replace_and_failure_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            old = [body("old")]
            new = [body("new")]
            catalog.write_catalog(path, old)
            real_replace = os.replace

            def check_replace(source, destination):
                self.assertEqual(Path(source).parent, path.parent)
                self.assertEqual(Path(destination), path)
                self.assertEqual(catalog.load_catalog(path), old)
                self.assertEqual(catalog.load_catalog(source), new)
                real_replace(source, destination)

            with mock.patch.object(catalog.os, "replace", side_effect=check_replace) as replace:
                catalog.write_catalog(path, new)
                replace.assert_called_once()
            self.assertEqual(catalog.load_catalog(path), new)
            for invalid in ([body(radius=0)], [body(extra=float("nan"))], [body(extra=float("inf"))]):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    catalog.write_catalog(path, invalid)
                self.assertEqual(catalog.load_catalog(path), new)
                self.assertEqual(list(Path(directory).iterdir()), [path])
            with mock.patch.object(catalog.os, "replace", side_effect=OSError("replace failed")), self.assertRaises(OSError):
                catalog.write_catalog(path, old)
            self.assertEqual(catalog.load_catalog(path), new)
            self.assertEqual(list(Path(directory).iterdir()), [path])


class AppTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            body("custom-sun", kind="star", name="Sun", jpl_command="10"),
            body("custom-world", name="Земля", latin="Terra", description="Blue marble",
                 facts=["Liquid oceans"], mythology="Gaia legend", history="Ancient chronicles",
                 parent="custom-sun", jpl_command="399"),
            body("no-command", name="No command"),
            body("far-star", name="Distant", kind="star", scale="local"),
        ]
        context = isolated_app(self.items)
        self.app: Any = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def response(self, text):
        return io.BytesIO(json.dumps({"result": text}).encode("utf-8"))

    def test_health_search_and_kind_keep_envelopes(self):
        self.assertEqual(self.app.health(), {"status": "ok", "objects": 4})
        self.assertEqual(self.app.objects(), self.items)
        for query in ("ЗЕМЛЯ", "terra", "BLUE", "OCEANS", "gaia", "CHRONICLES"):
            with self.subTest(query=query):
                self.assertEqual([item["id"] for item in self.app.objects(q=query)], ["custom-world"])
        self.assertEqual(self.app.objects(q="oceans", kind="star"), [])
        self.assertEqual(self.app.objects(q="absent"), [])
        self.assertEqual(len(self.app.objects(kind="star")), 2)
        routes = {route.path for route in self.app.app.routes}
        self.assertTrue({"/api/health", "/api/objects", "/api/live-ephemeris"} <= routes)

    def test_horizons_parameters_first_row_and_axis_swap(self):
        text = "header,not,data\n$$SOE\r\n\r\n 2460000.5, A.D. 2026-Sep-17, 1.25E+00, -2.5E+00, 3.75E-01, 9, 8, 7,\r\n2460001.5, later, 4, 5, 6,\r\n$$EOE\nfooter"
        with mock.patch.object(self.app.urllib.request, "urlopen", return_value=self.response(text)) as urlopen:
            self.assertEqual(self.app.fetch_jpl_vector("DES=1;"), {"x": 1.25, "y": 0.375, "z": -2.5})
        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        expected = {"COMMAND": "'DES=1;'", "CENTER": "'@10'", "OUT_UNITS": "AU-D",
                    "VEC_TABLE": "2", "VEC_CORR": "NONE", "REF_PLANE": "ECLIPTIC",
                    "EPHEM_TYPE": "VECTORS", "CSV_FORMAT": "YES", "format": "json"}
        for key, value in expected.items():
            self.assertEqual(query[key], [value])
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 10)

    def test_horizons_rejects_missing_malformed_or_nonfinite_data(self):
        texts = ["", "$$SOE\n1,date,1,2,3", "1,date,1,2,3\n$$EOE",
                 "$$SOE\n\n$$EOE", "$$SOE\n1,date,1,2\n$$EOE", None]
        for coordinate in ("nan", "inf", "-inf", "not-a-number", "1e999"):
            for axis in range(3):
                coordinates = ["1", "2", "3"]
                coordinates[axis] = coordinate
                texts.append("$$SOE\n1,date," + ",".join(coordinates) + "\n$$EOE")
        for text in texts:
            with self.subTest(text=text), mock.patch.object(
                self.app.urllib.request, "urlopen", return_value=self.response(text)
            ):
                self.assertIsNone(self.app.fetch_jpl_vector("399"))

    def test_live_positions_use_catalog_ids_and_cache(self):
        vector = {"x": 1, "y": 3, "z": 2}
        with mock.patch.object(self.app, "fetch_jpl_vector", return_value=vector) as fetch:
            result = self.app.live_ephemeris()
            self.assertEqual(fetch.call_args_list, [mock.call("10"), mock.call("399")])
            self.assertEqual(set(result), {"timestamp", "positions", "source"})
            self.assertEqual(result["positions"], {"custom-sun": vector, "custom-world": vector})
            cached = self.app.live_ephemeris()
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(cached["positions"], result["positions"])
            self.assertEqual(cached["timestamp"], result["timestamp"])
            self.assertEqual(cached["source"], "NASA JPL Horizons (cached)")
        # Commands are derived from the current catalog at request time, not a static map.
        self.app.EPHEMERIS_CACHE["timestamp"] = None
        self.app.CATALOG = [body("new-id", jpl_command="499")]
        with mock.patch.object(self.app, "fetch_jpl_vector", return_value=vector) as fetch:
            self.assertEqual(self.app.live_ephemeris()["positions"], {"new-id": vector})
            fetch.assert_called_once_with("499")

    def test_live_partial_and_total_network_failure(self):
        vector = {"x": 1, "y": 2, "z": 3}
        with mock.patch.object(self.app, "fetch_jpl_vector", side_effect=[OSError("offline"), vector]), mock.patch("builtins.print"):
            self.assertEqual(self.app.live_ephemeris()["positions"], {"custom-world": vector})
        self.app.EPHEMERIS_CACHE = {"timestamp": None, "data": {}}
        with mock.patch.object(self.app, "fetch_jpl_vector", side_effect=OSError("offline")), mock.patch("builtins.print"):
            result = self.app.live_ephemeris()
        self.assertEqual(result["positions"], {})
        self.assertEqual(result["source"], "NASA JPL Horizons Live Ephemeris")
        self.assertIsNone(self.app.EPHEMERIS_CACHE["timestamp"])

    def test_app_import_from_backend_directory(self):
        # The subprocess must import app.py without relying on a generated
        # catalog: it points ASTROVERSE_CATALOG_PATH at the isolated temp file.
        result = subprocess.run(
            [sys.executable, "-c", "import app; print(app.health()['objects'])"],
            cwd=ROOT / "backend", capture_output=True, text=True, timeout=15, check=False,
            env={**os.environ, "ASTROVERSE_CATALOG_PATH": str(self.app.DATA_PATH)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "4")

    def test_invalid_catalog_fails_at_startup(self):
        self.app.DATA_PATH.write_text('[{"id":"invalid"}]', encoding="utf-8")
        spec = importlib.util.spec_from_file_location("astroverse_invalid_app", ROOT / "backend" / "app.py")
        assert spec is not None and spec.loader is not None
        with self.assertRaises(ValueError):
            spec.loader.exec_module(importlib.util.module_from_spec(spec))


if __name__ == "__main__":
    unittest.main()
