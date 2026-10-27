"""FastAPI endpoint tests: /api/health, /api/objects, /api/live-ephemeris."""

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import app, fetch_jpl_vector


def isolated_app(catalog):
    """Build an app instance with an isolated in-memory catalog."""
    import importlib

    with patch.object(app_module, "CATALOG", catalog):
        importlib.reload(app_module)
        return app_module.app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            {"id": "sun", "name": "Солнце", "kind": "star", "scale": "solar",
             "jpl_command": "Sun", "name_latin": "Sol", "description": "star",
             "facts": [], "mythology": "", "history": ""},
            {"id": "earth", "name": "Земля", "kind": "planet", "scale": "solar",
             "jpl_command": "Earth", "name_latin": "Terra", "description": "home",
             "facts": ["blue"], "mythology": "", "history": ""},
            {"id": "proxima", "name": "Proxima", "kind": "star", "scale": "local",
             "jpl_command": None, "name_latin": "", "description": "near",
             "facts": [], "mythology": "", "history": ""},
        ]
        self.client = TestClient(isolated_app(self.catalog))

    def test_health_search_and_kind_keep_envelopes(self):
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "objects": 3})

        resp = self.client.get("/api/objects")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 3)

        resp = self.client.get("/api/objects?q=земля")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "earth")

        resp = self.client.get("/api/objects?kind=planet")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "earth")

        # Envelope is preserved: no wrapping object, plain list.
        self.assertIsInstance(resp.json(), list)

    def test_horizons_parameters_first_row_and_axis_swap(self):
        raw = (
            "$$SOE\n"
            " 1234, Earth, 1.0, 2.0, 3.0, 0.1, 0.2, 0.3,\n"
            "$$EOE\n"
        )
        payload = {"result": raw}
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                json.dumps(payload).encode()
            )
            vec = fetch_jpl_vector("Earth")
        self.assertIsNotNone(vec)
        # JPL Z becomes Three.js Y and vice versa.
        self.assertEqual(vec, {"x": 1.0, "y": 3.0, "z": 2.0})

    def test_horizons_rejects_missing_malformed_or_nonfinite_data(self):
        # Missing result block.
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                json.dumps({"result": "nothing"}).encode()
            )
            self.assertIsNone(fetch_jpl_vector("Earth"))

        # Empty block.
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                json.dumps({"result": "$$SOE\n$$EOE\n"}).encode()
            )
            self.assertIsNone(fetch_jpl_vector("Earth"))

        # Non-finite values.
        raw = "$$SOE\n 1, Earth, inf, 2, 3, 0, 0, 0,\n$$EOE\n"
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value.read.return_value = (
                json.dumps({"result": raw}).encode()
            )
            self.assertIsNone(fetch_jpl_vector("Earth"))

    def test_live_positions_use_catalog_ids_and_cache(self):
        vec = {"x": 1.0, "y": 2.0, "z": 3.0}
        with patch.object(app_module, "fetch_jpl_vector", return_value=vec):
            resp = self.client.get("/api/live-ephemeris")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            # Only solar objects with jpl_command are included.
            self.assertIn("earth", data["positions"])
            self.assertIn("sun", data["positions"])
            self.assertNotIn("proxima", data["positions"])
            self.assertEqual(data["positions"]["earth"], vec)

            # Second call within the cache window must reuse stored data.
            resp2 = self.client.get("/api/live-ephemeris")
            self.assertEqual(resp2.json()["positions"], data["positions"])

    def test_live_partial_and_total_network_failure(self):
        def flaky(cmd):
            if cmd == "Earth":
                raise RuntimeError("network down")
            return {"x": 1.0, "y": 2.0, "z": 3.0}

        with patch.object(app_module, "fetch_jpl_vector", side_effect=flaky):
            resp = self.client.get("/api/live-ephemeris")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            # Partial failure: Sun survives, Earth is skipped.
            self.assertIn("sun", data["positions"])
            self.assertNotIn("earth", data["positions"])

        with patch.object(app_module, "fetch_jpl_vector", side_effect=RuntimeError):
            resp = self.client.get("/api/live-ephemeris")
            self.assertEqual(resp.status_code, 200)
            # Total failure: still 200, empty positions.
            self.assertEqual(resp.json()["positions"], {})

    def test_app_import_from_backend_directory(self):
        # Importing from the backend directory must work (WORKDIR is /app/backend).
        import subprocess

        result = subprocess.run(
            [sys.executable, "-c", "from app import app; assert app is not None"],
            cwd=str(ROOT / "backend"),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_catalog_fails_at_startup(self):
        from data.catalog import write_catalog

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            with open(path, "w") as f:
                json.dump([{"id": "bad"}], f)
            with patch.dict("os.environ", {"ASTROVERSE_CATALOG_PATH": str(path)}):
                with self.assertRaises(Exception):
                    import data.catalog
                    importlib.reload(data.catalog)
                    data.catalog.load_catalog()

    # ---- /api/objects edge cases ----

    def test_objects_empty_catalog(self):
        empty_app = isolated_app([])
        client = TestClient(empty_app)
        resp = client.get("/api/objects")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_objects_search_no_matches(self):
        resp = self.client.get("/api/objects?q=zzznonexistent")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_objects_search_case_insensitive(self):
        resp = self.client.get("/api/objects?q=ЗЕМЛЯ")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "earth")

    def test_objects_kind_no_matches(self):
        resp = self.client.get("/api/objects?kind=black_hole")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_objects_q_and_kind_combined(self):
        resp = self.client.get("/api/objects?q=earth&kind=planet")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["id"], "earth")

    def test_objects_q_and_kind_no_overlap(self):
        resp = self.client.get("/api/objects?q=earth&kind=star")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    # ---- /api/live-ephemeris edge cases ----

    def test_live_ephemeris_empty_catalog(self):
        empty_app = isolated_app([])
        client = TestClient(empty_app)
        resp = client.get("/api/live-ephemeris")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["positions"], {})

    def test_live_ephemeris_no_solar_objects(self):
        catalog = [
            {"id": "proxima", "name": "Proxima", "kind": "star", "scale": "local",
             "jpl_command": None, "name_latin": "", "description": "near",
             "facts": [], "mythology": "", "history": ""},
        ]
        app_no_solar = isolated_app(catalog)
        client = TestClient(app_no_solar)
        resp = client.get("/api/live-ephemeris")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["positions"], {})

    def test_live_ephemeris_cache_expires_after_hour(self):
        vec = {"x": 1.0, "y": 2.0, "z": 3.0}
        with patch.object(app_module, "fetch_jpl_vector", return_value=vec):
            resp = self.client.get("/api/live-ephemeris")
            first = resp.json()["timestamp"]

        import datetime as dt
        fake_now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)

        with patch.object(app_module.datetime, "now", return_value=fake_now):
            with patch.object(app_module, "fetch_jpl_vector", return_value={"x": 9.0, "y": 9.0, "z": 9.0}) as mock_fetch:
                resp2 = self.client.get("/api/live-ephemeris")
                self.assertEqual(resp2.json()["positions"]["earth"], {"x": 9.0, "y": 9.0, "z": 9.0})
                mock_fetch.assert_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
