"""API cache eviction, HTTP policy and malformed upstream response regressions."""

import importlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.test_api import isolated_app
from backend import app as api


class ApiEdges(unittest.TestCase):
    def setUp(self):
        self.objects = [dict(id="a", name="А", kind="star", scale="local")]
        self.client = TestClient(isolated_app(self.objects))

    def test_binary_cache_lru_eviction_and_disabled_mode(self):
        with patch.object(api, "BINARY_CACHE_MAX", 2):
            a = api.binary_payload("v2", "a", None, None, self.objects)
            api.binary_payload("v2", "b", None, None, self.objects)
            self.assertIs(api.binary_payload("v2", "a", None, None, []), a)
            api.binary_payload("v2", "c", None, None, [])
            self.assertEqual([key[1] for key in api.BINARY_CACHE], ["a", "c"])
        api.BINARY_CACHE.clear()
        with patch.object(api, "BINARY_CACHE_MAX", 0):
            api.binary_payload("v1", None, None, None, self.objects)
        self.assertEqual(len(api.BINARY_CACHE), 0)

    def test_etag_lists_wildcards_and_missing_file_revision(self):
        self.assertTrue(api.etag_matches('*', '"x"'))
        self.assertTrue(api.etag_matches('"y", W/"x"', '"x"'))
        self.assertFalse(api.etag_matches('"y"', '"x"'))
        self.assertFalse(api.etag_matches(None, '"x"'))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(api.catalog_revision(Path(directory) / "missing"), "0")
        first = self.client.get("/api/objects?format=v2")
        cached = self.client.get("/api/objects?format=v2", headers={"If-None-Match": '*'} )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")

    def test_expired_rate_limit_entries_are_removed(self):
        now = time.monotonic()
        api.RATE_LIMIT_STATE.update({(str(i), "/api/objects"): [now - 100, 10] for i in range(4100)})
        self.assertEqual(self.client.get("/api/objects").status_code, 200)
        self.assertLess(len(api.RATE_LIMIT_STATE), 5)

    def test_cors_is_explicit_and_never_wildcard_with_credentials(self):
        with patch.dict(os.environ, {"ASTROVERSE_CORS_ORIGINS": " https://allowed.test, "}):
            app = importlib.reload(api).app
            response = TestClient(app).get("/api/health", headers={"Origin": "https://allowed.test"})
            self.assertEqual(response.headers["access-control-allow-origin"], "https://allowed.test")
            rejected = TestClient(app).get("/api/health", headers={"Origin": "https://other.test"})
            self.assertNotIn("access-control-allow-origin", rejected.headers)
        importlib.reload(api)

    def test_jpl_nontext_empty_short_and_invalid_vectors_return_unknown(self):
        for text in [None, 3, "$$SOE\n\n$$EOE", "$$SOE\n1,2,3\n$$EOE",
                     "$$SOE\n1,date,bad,2,3\n$$EOE", "$$SOE\n1,date,inf,2,3\n$$EOE"]:
            with self.subTest(text=text), patch("urllib.request.urlopen") as get:
                get.return_value.__enter__.return_value.read.return_value = json.dumps({"result": text}).encode()
                self.assertIsNone(api.fetch_jpl_vector("399"))
