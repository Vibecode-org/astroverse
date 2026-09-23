"""Offline/mocked source tests plus a bounded local HTTP integration test."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest.mock import patch

from data import build_catalog as builder
from data.catalog import load_catalog

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeClient:
    def get(self, url, params=None):
        if "TAP" in url:
            return [{"pl_name": "Test b", "hostname": "Test", "ra": 180, "dec": -20,
                     "sy_dist": 10, "pl_rade": None, "pl_bmasse": None,
                     "pl_orbper": 4, "pl_eqt": None, "st_teff": 5000,
                     "st_mass": 1, "st_spectype": "G", "discoverymethod": "Transit"}]
        name = "123 Test asteroid" if params["sb-kind"] == "a" else "123P/Test comet"
        return {"fields": ["diameter", "per", "pdes", "full_name", "a"],
                "data": [["20", "100", "123", name, "2.5"]]}


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "objects.json"

    def test_offline_independent_idempotent_and_same_population(self):
        items = builder.build_enriched_catalog(output=self.output, offline=True)
        first = self.output.read_bytes()
        builder.build_enriched_catalog(output=self.output, offline=True)
        self.assertEqual(first, self.output.read_bytes())
        self.assertEqual(len(items), len({o["id"] for o in items}))
        self.assertEqual([o["jpl_command"] for o in items if "jpl_command" in o],
                         ["199", "299", "399", "499", "599", "699", "799", "899", "999"])
        self.assertNotIn("Условия и феномены мира", first.decode())

    def test_online_normalization_and_unknown_measurements(self):
        items = builder.build_enriched_catalog(output=self.output, client=FakeClient())
        by_id = {o["id"]: o for o in items}
        planet = by_id["test_b"]
        self.assertEqual(planet["parent"], "test")
        self.assertEqual(planet["ra"], 12)
        self.assertEqual(planet["dec"], -20)
        self.assertAlmostEqual(planet["distance_ly"], 32.61563777)
        for field in ("mass_earth", "radius_earth", "temperature_k"):
            self.assertIsNone(planet[field])
        self.assertNotIn("gravity", planet)
        self.assertEqual(by_id["123_test_asteroid"]["radius_km"], 10)
        self.assertEqual(by_id["123p_test_comet"]["period_days"], 100)
        self.assertNotIn("jpl_command", by_id["123_test_asteroid"])
        self.assertEqual(items, load_catalog(self.output))

    def test_jpl_provisional_suffix_preserves_existing_id(self):
        config = builder.load_config(builder.DEFAULT_CONFIG)
        identities = builder.identity_index(load_catalog(ROOT / "data" / "catalog_seed.json"))
        response = {"fields": ["full_name", "pdes", "a", "per", "diameter"],
                    "data": [["1 Ceres (A801 AA)", "1", "2.766", "1680", "939.4"]]}
        with patch.object(FakeClient, "get", return_value=response):
            items = builder.fetch_small_bodies(FakeClient(), config, identities, "asteroid", 1)
        self.assertEqual(items[0]["id"], "1_ceres")

    def test_failed_source_keeps_output(self):
        self.output.write_text("previous contents", encoding="utf-8")
        with patch.object(FakeClient, "get", side_effect=builder.SourceError("offline")):
            with self.assertRaises(builder.SourceError):
                builder.build_enriched_catalog(output=self.output, client=FakeClient())
        self.assertEqual(self.output.read_text(), "previous contents")

    def test_seed_cannot_be_overwritten(self):
        with self.assertRaises(ValueError):
            builder.build_enriched_catalog(output=ROOT / "data" / "catalog_seed.json", offline=True)

    def test_duplicate_records_fail_before_replace(self):
        real_get = FakeClient.get

        def get(client, url, params=None):
            result = real_get(client, url, params)
            return result * 2 if isinstance(result, list) else result

        with patch.object(FakeClient, "get", get), self.assertRaisesRegex(ValueError, "duplicate id"):
            builder.build_enriched_catalog(output=self.output, client=FakeClient())
        self.assertFalse(self.output.exists())

    def test_missing_parent_fails_before_replace(self):
        with patch.object(builder, "fetch_exoplanets", return_value=[
            {"id": "test", "name": "Test", "kind": "exoplanet", "scale": "local", "parent": "absent"}
        ]), self.assertRaisesRegex(ValueError, "unknown parent"):
            builder.build_enriched_catalog(output=self.output, client=FakeClient())
        self.assertFalse(self.output.exists())

    def test_wikipedia_replaces_not_appends(self):
        items = [{"id": "earth", "wikipedia_title": "Земля", "description": "old"}]
        config = builder.load_config(builder.DEFAULT_CONFIG)
        with patch.object(FakeClient, "get", return_value={"extract": "A sourced description"}):
            builder.enrich_wikipedia(items, FakeClient(), config)
            first = copy.deepcopy(items)
            builder.enrich_wikipedia(items, FakeClient(), config)
        self.assertEqual(items, first)
        self.assertEqual(items[0]["description"], "A sourced description")

    def test_cli_environment_path_from_other_directory(self):
        result = subprocess.run([sys.executable, str(ROOT / "data" / "build_catalog.py"), "--offline"],
                                cwd=self.temp.name, env={**os.environ, "ASTROVERSE_CATALOG_PATH": str(self.output)},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(load_catalog(self.output))

    def test_http_build_to_backend(self):
        import uvicorn
        items = builder.build_enriched_catalog(output=self.output, offline=True)
        with patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": str(self.output)}):
            spec = importlib.util.spec_from_file_location("integration_app", ROOT / "backend" / "app.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        sock = socket.socket()
        self.addCleanup(sock.close)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(module.app, log_level="error", loop="asyncio", lifespan="off"))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(server.started, "Backend did not start within 10 seconds")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/api/objects", timeout=10) as response:
                served = json.load(response)
            self.assertEqual(served, items)
            self.assertEqual({o["id"] for o in served}, {o["id"] for o in items})
            with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=10) as response:
                self.assertEqual(json.load(response)["objects"], len(items))
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            sock.close()
        self.assertFalse(thread.is_alive(), "Backend did not stop")


if __name__ == "__main__":
    unittest.main()
