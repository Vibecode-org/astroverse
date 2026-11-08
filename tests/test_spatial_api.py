"""Disk/runtime contracts, HTTP budgets, consistency and legacy wire regression."""

import copy
import math
import os
import sqlite3
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.byte_cache import ByteLRU
from backend.sector_api import MAX_RESPONSE_BYTES, install_sector_api
from data.catalog import encode_binary_catalog, encode_binary_catalog_v2
from data.coordinates import coordinate_contract, snapshot_coordinates
from data.runtime_catalog import DiskCatalog
from data.sectors import ResultLimitExceeded, SectorIndex, build_sector_index, physical_position
from tests.test_api import isolated_app
from backend import app as api
from tests.test_sectors import star


class SpatialTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": str(Path(__file__).resolve().parents[1] / "data/catalog_seed.json")})
        env.start()
        self.addCleanup(env.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "index.sqlite"
        self.items = [star("b", 12, facts=["Кириллица"]), star("a", 10),
                      star("far", 100), star("unknown", None),
                      dict(id="child", name="child", kind="exoplanet", scale="local", parent="a"),
                      dict(id="sun", name="Sun", kind="star", scale="solar", source="seed")]
        self.build()
        self.disk = DiskCatalog(self.path)
        self.app = FastAPI()
        install_sector_api(self.app, self.disk, api.etag_matches, 8192)
        self.client = TestClient(self.app)
        self.prefix = "/api/spatial/v1"
        self.sid = SectorIndex(self.path).locate("a")

    def build(self):
        build_sector_index(self.path, self.items)

    def nearby(self, **kwargs):
        return self.client.get(self.prefix + "/nearby", params=dict(
            scale="local", frame="equatorial", x=0, y=0, z=0, radius=32, **kwargs))

    def test_contract_preserves_unknown_metadata_and_synthetic(self):
        contract = self.client.get(self.prefix + "/contract").json()
        self.assertEqual(contract, coordinate_contract())
        for field in ("source_epoch", "reference_system", "evaluated_at", "accuracy", "time_scale"):
            self.assertIsNone(contract[field])
        for oid, expected in (("unknown", "unknown"), ("a", "unverified"), ("sun", "unknown")):
            row = self.client.get(self.prefix + f"/objects/{oid}/sector").json()
            self.assertEqual(row["coordinates"]["status"], expected)
            self.assertIsNone(row["coordinates"]["simulation_position"])
            self.assertIsNone(row["coordinates"]["source_epoch"])
        obj = snapshot_coordinates(star("stress", 10, source="synthetic"))
        self.assertEqual(obj["status"], "synthetic")
        self.assertIsNone(obj["accuracy"])

    def test_time_requests_never_silently_return_snapshot(self):
        for endpoint in ("/nearby?scale=local&frame=equatorial&x=0&y=0&z=0",
                         f"/sectors/{self.sid}?", "/objects/a/sector?"):
            for at in ("now", "2000-01-01T12:00:00Z", "garbage", ""):
                response = self.client.get(self.prefix + endpoint + "&at=" + at)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["detail"]["code"], "unsupported_simulation_time")

    def test_nearby_selection_membership_and_pagination(self):
        response = self.nearby()
        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["id"] for s in response.json()["sectors"]], [self.sid])
        snapshot = response.json()["snapshot"]
        page1 = self.client.get(self.prefix + f"/sectors/{self.sid}", params={"limit": 2, "snapshot": snapshot}).json()
        self.assertEqual([o["object"]["id"] for o in page1["objects"]], ["a", "b"])
        page2 = self.client.get(self.prefix + f"/sectors/{self.sid}", params={"limit": 2, "after": page1["next_after"]}).json()
        self.assertEqual([o["object"]["id"] for o in page2["objects"]], ["child"])
        self.assertIsNone(page2["next_after"])
        self.assertIsNone(page2["objects"][0]["coordinates"]["position"])
        self.assertEqual(self.client.get(self.prefix + f"/sectors/{self.sid}?after=zz").json()["objects"], [])
        self.assertEqual(self.client.get(self.prefix + "/objects/child/sector").json()["sector"]["id"], self.sid)
        self.assertEqual(self.client.get(self.prefix + "/objects/unknown/sector").json()["sector"]["id"], "local:unlocated")

    def test_http_input_bounds_and_missing_objects(self):
        for params in ({"x": "nan"}, {"y": "inf"}, {"z": "1e300"}, {"radius": "nan"},
                       {"radius": -1}, {"radius": 1000001}, {"limit": 129}, {"limit": 0},
                       {"frame": "ICRS"}, {"scale": "solar"}):
            base = dict(scale="local", frame="equatorial", x=0, y=0, z=0)
            base.update(params)
            self.assertEqual(self.client.get(self.prefix + "/nearby", params=base).status_code, 422)
        for suffix in ("/objects/absent/sector", "/sectors/absent"):
            self.assertEqual(self.client.get(self.prefix + suffix).status_code, 404)
        for query in ("limit=0", "limit=513", "limit=bad", "after=" + "a" * 513):
            self.assertEqual(self.client.get(self.prefix + f"/sectors/{self.sid}?{query}").status_code, 422)
        for path in ("/objects/a/sector", f"/sectors/{self.sid}", "/nearby?scale=local&frame=equatorial&x=0&y=0&z=0"):
            separator = "&" if "?" in path else "?"
            self.assertEqual(self.client.get(self.prefix + path + separator + "snapshot=obsolete").status_code, 409)

    def test_spatial_overflow_and_byte_budget_are_explicit_errors(self):
        result = self.client.get(self.prefix + "/nearby", params=dict(
            scale="local", frame="equatorial", x=0, y=0, z=0, radius=200, limit=1))
        self.assertEqual(result.status_code, 413)
        with self.assertRaises(ResultLimitExceeded):
            SectorIndex(self.path).nearby("local", "equatorial", (0, 0, 0), 200, limit=1)
        for budget in (10, 1500):
            with patch("backend.sector_api.MAX_RESPONSE_BYTES", budget):
                self.assertEqual(self.client.get(self.prefix + f"/sectors/{self.sid}").status_code, 413)

    def test_conditional_requests_cannot_bypass_spatial_or_response_limits(self):
        nearby_url = self.prefix + "/nearby"
        params = dict(scale="local", frame="equatorial", x=0, y=0, z=0,
                      radius=200, limit=1)
        for headers in ({}, {"If-None-Match": "*"}, {"If-None-Match": '"unrelated"'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.get(nearby_url, params=params, headers=headers).status_code, 413)
                with patch("backend.sector_api.MAX_RESPONSE_BYTES", 1500):
                    self.assertEqual(self.client.get(self.prefix + f"/sectors/{self.sid}", headers=headers).status_code, 413)
        # A valid uncached representation can still revalidate with '*'. Once
        # cached, a conditional request should reuse it without rereading rows.
        url = self.prefix + f"/sectors/{self.sid}?limit=1"
        first = self.client.get(url, headers={"If-None-Match": "*"})
        self.assertEqual(first.status_code, 304)
        self.assertEqual(first.content, b"")
        with patch("data.runtime_catalog.Snapshot.select", side_effect=AssertionError("cache miss")):
            cached = self.client.get(url, headers={"If-None-Match": first.headers["etag"]})
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")

    def test_pagination_lookahead_does_not_load_an_oversized_next_object(self):
        self.items = [star(oid, 10) for oid in ("a", "b", "c")]
        self.items[1]["description"] = "x" * (MAX_RESPONSE_BYTES + 100)
        self.build()
        url = self.prefix + f"/sectors/{self.sid}"
        first = self.client.get(url, params={"limit": 1})
        self.assertEqual(first.status_code, 200, first.text[:200])
        self.assertEqual([row["object"]["id"] for row in first.json()["objects"]], ["a"])
        self.assertEqual(first.json()["next_after"], "a")
        for headers in ({}, {"If-None-Match": "*"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.client.get(url, params={"limit": 1, "after": "a"},
                                                 headers=headers).status_code, 413)
        last = self.client.get(url, params={"limit": 1, "after": "b"})
        self.assertEqual(last.status_code, 200)
        self.assertEqual([row["object"]["id"] for row in last.json()["objects"]], ["c"])
        self.assertIsNone(last.json()["next_after"])

    def test_byte_budget_counts_only_objects_in_the_requested_page(self):
        self.items = [star(oid, 10, description="x" * (MAX_RESPONSE_BYTES // 2))
                      for oid in ("a", "b")]
        self.build()
        url = self.prefix + f"/sectors/{self.sid}"
        first = self.client.get(url, params={"limit": 1})
        self.assertEqual(first.status_code, 200, first.text[:200])
        self.assertEqual(first.json()["next_after"], "a")
        second = self.client.get(url, params={"limit": 1, "after": "a"})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["objects"][0]["object"]["id"], "b")
        self.assertIsNone(second.json()["next_after"])
        self.assertEqual(self.client.get(url, params={"limit": 2}).status_code, 413)

    def test_etags_cache_and_revision_changes(self):
        url = self.prefix + f"/sectors/{self.sid}"
        first = self.client.get(url)
        etag = first.headers["etag"]
        for validator in (etag, "W/" + etag, '"other", W/' + etag, "*"):
            cached = self.client.get(url, headers={"If-None-Match": validator})
            self.assertEqual(cached.status_code, 304)
            self.assertEqual(cached.content, b"")
        self.assertNotEqual(self.client.get(url + "?limit=1").headers["etag"], etag)
        with patch("data.runtime_catalog.Snapshot.select", side_effect=AssertionError("cache miss")):
            self.assertEqual(self.client.get(url).content, first.content)
        before = self.nearby()
        self.items[2]["name"] = "unrelated change"
        self.build()
        self.assertEqual(self.client.get(url).headers["etag"], etag)
        revalidated = self.client.get(url, headers={"If-None-Match": etag})
        self.assertEqual(revalidated.status_code, 304)
        self.assertNotEqual(revalidated.headers["x-catalog-snapshot"], first.headers["x-catalog-snapshot"])
        self.assertNotEqual(self.nearby().headers["etag"], before.headers["etag"])
        self.assertEqual(self.client.get(url, params={"snapshot": before.json()["snapshot"]},
                                         headers={"If-None-Match": etag}).status_code, 409)
        self.items[0]["name"] = "local change"
        self.build()
        changed = self.client.get(url, headers={"If-None-Match": etag})
        self.assertEqual(changed.status_code, 200)
        self.assertNotEqual(changed.headers["etag"], etag)
        self.assertLessEqual(self.app.state.sector_cache.bytes, 8192)

    def test_root_motion_rebuild_relocates_family_and_rejects_time(self):
        old_sid = self.sid
        self.items[1]["distance_ly"] = 200
        self.build()
        index = SectorIndex(self.path)
        self.assertNotEqual(index.locate("a"), old_sid)
        self.assertEqual(index.locate("a"), index.locate("child"))
        self.assertEqual(self.client.get(self.prefix + "/objects/a/sector?at=now").status_code, 422)

    def test_snapshot_revision_includes_partition_and_coordinate_contract(self):
        before = self.nearby().json()["snapshot"]
        previous_sector = SectorIndex(self.path).sectors()[0]["revision"]
        build_sector_index(self.path, self.items, cell_size_ly=16)
        self.assertNotEqual(self.nearby().json()["snapshot"], before)
        changed_contract = dict(coordinate_contract(), source="test provenance change")
        with patch("data.coordinates.coordinate_contract", return_value=changed_contract):
            self.build()
        self.assertNotEqual(self.nearby().json()["snapshot"], before)
        self.assertNotEqual(SectorIndex(self.path).sectors()[0]["revision"], previous_sector)

    def test_pinned_transaction_survives_atomic_replacement(self):
        with self.disk.snapshot() as old:
            rev = old.metadata["catalog_revision"]
            self.items[1]["distance_ly"] = 200
            self.build()
            self.assertEqual(old.object("a")["distance_ly"], 10)
            self.assertEqual(old.locate("a"), self.sid)
        with self.disk.snapshot() as new:
            self.assertNotEqual(new.metadata["catalog_revision"], rev)
            self.assertEqual(new.object("a")["distance_ly"], 200)

    def test_unavailable_and_incompatible_artifact_return_503(self):
        self.path.unlink()
        response = self.nearby()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.build()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
            db.commit()
        self.assertEqual(self.nearby().status_code, 503)

    def test_runtime_legacy_json_search_details_and_binary_bytes(self):
        client = TestClient(isolated_app([]))
        with patch.object(api, "CATALOG", self.disk):
            self.assertEqual(client.get("/api/health").json()["objects"], len(self.items))
            self.assertEqual(client.get("/api/objects").json(), self.items)
            self.assertEqual(client.get("/api/objects/a").json(), self.items[1])
            self.assertEqual(client.get("/api/objects/absent").status_code, 404)
            self.assertEqual(client.get("/api/search?q=кириллица").json()[0]["id"], "b")
            self.assertEqual(client.get("/api/search?q=").json(), [])
            self.assertEqual(client.get("/api/objects?q=%20%20").json(), [])
            self.assertEqual(client.get("/api/objects?q=кириллица&kind=&scale=").json(), [self.items[0]])
            self.assertEqual(api.matching_items("Кириллица"), [self.items[0]])
            self.assertEqual(list(self.disk), self.items)
            for version, encoder, headers in (("v2", encode_binary_catalog_v2, {}),
                                              ("v1", encode_binary_catalog, {"Accept": "application/octet-stream"})):
                url = "/api/objects" + ("?format=v2" if version == "v2" else "")
                first = client.get(url, headers=headers)
                self.assertEqual(first.content, encoder(self.items))
                self.assertEqual(int(first.headers["content-length"]), len(first.content))
                self.assertEqual(first.headers["x-object-count"], str(len(self.items)))
                self.assertEqual(client.get(url, headers={**headers, "If-None-Match": first.headers["etag"]}).status_code, 304)
                for _ in range(2):
                    filtered = client.get(url + ("&" if "?" in url else "?") + "kind=exoplanet", headers=headers)
                    self.assertEqual(filtered.content, encoder([self.items[4]]))
                    self.assertEqual(filtered.headers["x-object-count"], "1")
            self.assertEqual(client.get("/api/objects?scale=solar").json(), [self.items[-1]])
            with patch.object(api, "LEGACY_FILTER_MAX_OBJECTS", 1):
                self.assertEqual(client.get("/api/objects?kind=star").status_code, 413)
            with patch.object(api, "LEGACY_FILTER_MAX_BYTES", 2):
                self.assertEqual(client.get("/api/objects?q=far").status_code, 413)

    def test_disk_search_stays_bounded_when_legacy_config_disables_limit(self):
        self.items = [star(f"star{i}", None) for i in range(600)]
        self.build()
        client = TestClient(isolated_app([]))
        with patch.object(api, "CATALOG", self.disk):
            for configured, expected in ((0, 500), (-1, 500), (1000, 500), (1, 1)):
                with patch.object(api, "SEARCH_LIMIT", configured):
                    self.assertEqual(len(client.get("/api/search?q=star").json()), expected)


class ByteCacheTests(unittest.TestCase):
    def test_lru_bytes_replacement_oversize_and_disabled(self):
        cache = ByteLRU(550)
        cache.put("a", b"a")
        cache.put("b", b"b")
        self.assertEqual(cache.get("a"), b"a")
        cache.put("c", b"c")
        self.assertIsNone(cache.get("b"))
        cache.put("a", b"replaced")
        self.assertEqual(cache.get("a"), b"replaced")
        cache.put("a", b"x" * 551)
        self.assertIsNone(cache.get("a"))
        self.assertLessEqual(cache.bytes, 550)
        cache = ByteLRU(0)
        cache.put("x", b"")
        self.assertIsNone(cache.get("x"))


class CoordinateReferenceTests(unittest.TestCase):
    def test_source_name_and_unvalidated_extra_epoch_do_not_imply_icrs(self):
        item = star("unknown_metadata", 10, source="ICRS/J2000 example label", epoch="J2000", time_scale="TT")
        result = snapshot_coordinates(item)
        for field in ("source_epoch", "time_scale", "origin", "reference_system", "accuracy"):
            self.assertIsNone(result[field])
        self.assertEqual(result["status"], "unverified")

    def test_spherical_conversion_matches_erfa_reference(self):
        # Independent ERFA t_erfa_c.c:t_s2c numeric reference, retrieved
        # 2026-11-05: https://github.com/liberfa/erfa/blob/master/src/t_erfa_c.c
        # Generic spherical axes, unit radius, no celestial epoch/time scale:
        # this validates projection only, not a real body's ephemeris.
        expected = [-0.5366267667260523906, -0.8409302618566214041, 0.0697711109765145365]
        obj = star("reference", 1, ra=math.degrees(3.0123) / 15)
        obj["dec"] = math.degrees(-0.999)
        for actual, reference in zip(physical_position(obj)[1:], expected):
            self.assertAlmostEqual(actual, reference, delta=1e-12)
        obj = dict(distance_ly=1, galactic_l=math.degrees(3.0123), galactic_b=math.degrees(-0.999))
        for actual, reference in zip(physical_position(obj)[1:], expected):
            self.assertAlmostEqual(actual, reference, delta=1e-12)
