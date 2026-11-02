"""FastAPI endpoint tests: /api/health, /api/objects, /api/live-ephemeris."""

import importlib
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

# Importing backend.app loads a catalog immediately. Tests must not depend on
# data/objects.json, which is generated inside the container at startup.
if not os.environ.get("ASTROVERSE_CATALOG_PATH", "").strip():
    os.environ.pop("ASTROVERSE_CATALOG_PATH", None)
os.environ.setdefault("ASTROVERSE_CATALOG_PATH", str(ROOT / "data" / "catalog_seed.json"))

from fastapi.testclient import TestClient

from backend import app as app_module
from backend.app import app, fetch_jpl_vector


def isolated_app(catalog):
    """Build an app instance with an isolated in-memory catalog."""
    importlib.reload(app_module)
    app_module.CATALOG = catalog
    return app_module.app


class AppTests(unittest.TestCase):
    def setUp(self):
        self.catalog = [
            {"id": "sun", "name": "Солнце", "kind": "star", "scale": "solar",
             "jpl_command": "Sun", "latin": "Sol", "description": "star",
             "facts": [], "mythology": "", "history": ""},
            {"id": "earth", "name": "Земля", "kind": "planet", "scale": "solar",
             "jpl_command": "Earth", "latin": "Earth", "description": "home",
             "facts": ["blue"], "mythology": "", "history": ""},
            {"id": "proxima", "name": "Proxima", "kind": "star", "scale": "local",
             "jpl_command": None, "latin": "", "description": "near",
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
            # Второй запрос должен быть независим от кеша, накопленного выше.
            app_module.EPHEMERIS_CACHE["timestamp"] = None
            app_module.EPHEMERIS_CACHE["data"] = {}
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

    def test_objects_scale_filter(self):
        resp = self.client.get("/api/objects?scale=local")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual([item["id"] for item in data], ["proxima"])

    def test_object_detail_and_404(self):
        resp = self.client.get("/api/objects/earth")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], "earth")
        self.assertEqual(resp.json()["name"], "Земля")

        resp = self.client.get("/api/objects/does-not-exist")
        self.assertEqual(resp.status_code, 404)

    def test_binary_filtered_subset_with_dangling_parent(self):
        # A filtered subset contains children whose parent is outside the
        # subset. Validating it would raise "unknown parent" and make every
        # `?kind=` binary request a 500; the endpoint must encode instead.
        catalog = [
            {"id": "host", "name": "Host", "kind": "star", "scale": "local",
             "description": "", "facts": []},
            {"id": "child", "name": "Child", "kind": "planet", "scale": "solar",
             "parent": "host", "description": "", "facts": []},
        ]
        client = TestClient(isolated_app(catalog))
        resp = client.get(
            "/api/objects?kind=planet",
            headers={"Accept": "application/octet-stream"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/octet-stream")
        self.assertEqual(resp.headers["x-object-count"], "1")
        self.assertEqual(len(resp.content), 20 + 26)

        from data.catalog import FLAG_HAS_PARENT, read_binary_catalog

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subset.bin"
            path.write_bytes(resp.content)
            parsed = read_binary_catalog(path)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["flags"][0], FLAG_HAS_PARENT)
        self.assertEqual(parsed["parent_indices"][0], -1)

    def test_binary_response_is_cached_per_filter(self):
        headers = {"Accept": "application/octet-stream"}
        first = self.client.get("/api/objects", headers=headers)
        second = self.client.get("/api/objects", headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, second.content)
        self.assertEqual(len(app_module.BINARY_CACHE), 1)

    def test_rate_limit_returns_429(self):
        app_module.RATE_LIMIT_RULES["/api/objects"] = (2, 60.0)
        app_module.RATE_LIMIT_STATE.clear()
        try:
            self.assertEqual(self.client.get("/api/objects").status_code, 200)
            self.assertEqual(self.client.get("/api/objects").status_code, 200)
            resp = self.client.get("/api/objects")
            self.assertEqual(resp.status_code, 429)
            self.assertIn("Retry-After", resp.headers)
        finally:
            app_module.RATE_LIMIT_RULES["/api/objects"] = (600, 60.0)
            app_module.RATE_LIMIT_STATE.clear()

    def test_binary_v1_is_default_and_v2_is_explicit(self):
        from data.catalog import BINARY_VERSION_V2, read_binary_catalog

        headers = {"Accept": "application/octet-stream"}
        v1 = self.client.get("/api/objects", headers=headers)
        self.assertEqual(v1.status_code, 200)
        self.assertEqual(v1.headers["x-catalog-format"], "v1")

        v2 = self.client.get("/api/objects?format=v2")
        self.assertEqual(v2.status_code, 200)
        self.assertEqual(v2.headers["content-type"], "application/octet-stream")
        self.assertEqual(v2.headers["x-catalog-format"], "v2")
        self.assertEqual(v2.headers["x-object-count"], "3")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v2.bin"
            path.write_bytes(v2.content)
            parsed = read_binary_catalog(path)
        self.assertEqual(parsed["version"], BINARY_VERSION_V2)
        self.assertEqual(parsed["ids"], ["sun", "earth", "proxima"])
        self.assertEqual(parsed["names"][1], "Земля")
        self.assertEqual(parsed["parents"][0], None)

    def test_binary_v2_vendor_accept_and_filtered_subset(self):
        from data.catalog import FLAG_HAS_PARENT, read_binary_catalog

        resp = self.client.get(
            "/api/objects?kind=planet",
            headers={"Accept": "application/vnd.astroverse.catalog.v2"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["x-catalog-format"], "v2")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "subset.v2.bin"
            path.write_bytes(resp.content)
            parsed = read_binary_catalog(path)
        self.assertEqual(parsed["count"], 1)
        self.assertEqual(parsed["ids"], ["earth"])
        self.assertEqual(parsed["flags"][0], 0)

        # A subset whose parent is outside the subset must not 500.
        catalog = [
            {"id": "host", "name": "Host", "kind": "star", "scale": "local",
             "description": "", "facts": []},
            {"id": "child", "name": "Child", "kind": "planet", "scale": "solar",
             "parent": "host", "description": "", "facts": []},
        ]
        client = TestClient(isolated_app(catalog))
        resp = client.get("/api/objects?kind=planet&format=v2")
        self.assertEqual(resp.status_code, 200)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dangling.v2.bin"
            path.write_bytes(resp.content)
            parsed = read_binary_catalog(path)
        self.assertEqual(parsed["flags"][0], FLAG_HAS_PARENT)
        self.assertEqual(parsed["parent_indices"][0], -1)
        self.assertIsNone(parsed["parents"][0])

    def test_binary_cache_separates_v1_and_v2(self):
        app_module.BINARY_CACHE.clear()
        self.client.get("/api/objects", headers={"Accept": "application/octet-stream"})
        self.client.get("/api/objects?format=v2")
        formats = {key[0] for key in app_module.BINARY_CACHE}
        self.assertEqual(formats, {"v1", "v2"})

    def test_search_returns_compact_rows(self):
        resp = self.client.get("/api/search?q=земля")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(rows, [{
            "id": "earth", "name": "Земля", "latin": "Earth",
            "kind": "planet", "scale": "solar",
        }])

    def test_search_by_description_and_empty_query(self):
        # "home" only exists in Earth's description, not in its name/latin.
        resp = self.client.get("/api/search?q=home")
        self.assertEqual([row["id"] for row in resp.json()], ["earth"])
        self.assertEqual(self.client.get("/api/search?q=").json(), [])

    def test_search_respects_limit(self):
        original = app_module.SEARCH_LIMIT
        app_module.SEARCH_LIMIT = 1
        try:
            resp = self.client.get("/api/search?q=e")
            self.assertEqual(len(resp.json()), 1)
        finally:
            app_module.SEARCH_LIMIT = original

    # ---- catalog index (search / by-id) ----

    def test_index_matches_every_searched_field(self):
        # The index joins name/latin/description/facts/mythology/history into
        # one lowercase blob; each field must still be findable on its own.
        for query, expected in (
            ("земля", "earth"),      # name
            ("earth", "earth"),      # latin
            ("home", "earth"),       # description
            ("blue", "earth"),       # facts (a list, joined as text)
            ("near", "proxima"),     # description
            ("sol", "sun"),          # latin
        ):
            with self.subTest(query=query):
                ids = [row["id"] for row in self.client.get(f"/api/search?q={query}").json()]
                self.assertIn(expected, ids)

        # `?q=` on the full catalog endpoint uses the same index.
        data = self.client.get("/api/objects?q=home").json()
        self.assertEqual([item["id"] for item in data], ["earth"])

    def test_index_does_not_match_across_fields(self):
        # Newline is the field separator, so a query cannot span two fields.
        catalog = [
            {"id": "a", "name": "Alpha", "kind": "star", "scale": "local",
             "description": "beta", "facts": []},
        ]
        client = TestClient(isolated_app(catalog))
        self.assertEqual(client.get("/api/search?q=alpha%20beta").json(), [])
        self.assertEqual(len(client.get("/api/search?q=beta").json()), 1)

    def test_index_is_rebuilt_when_catalog_is_replaced(self):
        client = TestClient(isolated_app(self.catalog))
        self.assertEqual(len(client.get("/api/objects").json()), 3)
        self.assertEqual(client.get("/api/objects/earth").json()["id"], "earth")

        smaller = [self.catalog[0]]
        client = TestClient(isolated_app(smaller))
        self.assertEqual(len(client.get("/api/objects").json()), 1)
        # A stale index would still answer 200 with the removed object.
        self.assertEqual(client.get("/api/objects/earth").status_code, 404)
        self.assertEqual(client.get("/api/search?q=home").json(), [])

    # ---- caching ----

    def test_objects_are_revalidated_with_etag(self):
        first = self.client.get("/api/objects?format=v2")
        self.assertEqual(first.status_code, 200)
        etag = first.headers["etag"]
        self.assertTrue(etag.startswith('"') and etag.endswith('"'))
        self.assertIn("must-revalidate", first.headers["cache-control"])
        self.assertIn("Accept", first.headers["vary"])

        cached = self.client.get(
            "/api/objects?format=v2", headers={"If-None-Match": etag}
        )
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")
        self.assertEqual(cached.headers["etag"], etag)

        # Weak validators and lists are accepted, as browsers send them.
        for header in (f"W/{etag}", f'"other", {etag}'):
            with self.subTest(header=header):
                resp = self.client.get(
                    "/api/objects?format=v2", headers={"If-None-Match": header}
                )
                self.assertEqual(resp.status_code, 304)

        # A different representation must not be served from that validator.
        resp = self.client.get("/api/objects", headers={"If-None-Match": etag})
        self.assertEqual(resp.status_code, 200)

        # JSON responses carry their own validator and honour it too.
        json_first = self.client.get("/api/objects?scale=solar")
        json_etag = json_first.headers["etag"]
        self.assertEqual(
            self.client.get(
                "/api/objects?scale=solar", headers={"If-None-Match": json_etag}
            ).status_code,
            304,
        )
        self.assertNotEqual(json_etag, etag)

    def test_etag_changes_with_filter_and_catalog_revision(self):
        a = self.client.get("/api/objects?format=v2").headers["etag"]
        b = self.client.get("/api/objects?kind=planet&format=v2").headers["etag"]
        self.assertNotEqual(a, b)

        with patch.object(app_module, "CATALOG_REVISION", "999-1"):
            c = self.client.get("/api/objects?format=v2").headers["etag"]
        self.assertNotEqual(a, c)

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

        with patch.object(app_module, "utcnow", return_value=fake_now):
            with patch.object(app_module, "fetch_jpl_vector", return_value={"x": 9.0, "y": 9.0, "z": 9.0}) as mock_fetch:
                resp2 = self.client.get("/api/live-ephemeris")
                self.assertEqual(resp2.json()["positions"]["earth"], {"x": 9.0, "y": 9.0, "z": 9.0})
                mock_fetch.assert_called()

    def test_live_ephemeris_total_failure_is_negatively_cached(self):
        # An unreachable JPL must not be retried on every request: nine
        # 10-second outbound timeouts per page load would take the API down.
        with patch.object(
            app_module, "fetch_jpl_vector", side_effect=RuntimeError("down")
        ) as mock_fetch:
            first = self.client.get("/api/live-ephemeris")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.json()["positions"], {})
            calls_after_first = mock_fetch.call_count

            second = self.client.get("/api/live-ephemeris")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.json()["positions"], {})
            self.assertIn("unavailable", second.json()["source"])
            self.assertEqual(mock_fetch.call_count, calls_after_first)


if __name__ == "__main__":
    unittest.main(verbosity=2)
