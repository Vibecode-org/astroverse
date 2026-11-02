"""Smoke test: the frontend reads the v2 binary catalog (Phase 2.4).

These tests run against whatever catalog the stack serves (3 471 by default).
They assert the data path, not a specific object count:
- local/galaxy rows come from `/api/objects?format=v2`;
- the full JSON catalog is not requested on the normal path;
- ids/names survive the binary roundtrip, selection and search still work;
- view switching does not grow GPU resource counters.
"""
import gzip
import urllib.request

import pytest

from common import INSTALL_PROBE, URL, switch_view, wait_lod_settled, wait_row, wait_state

pytestmark = pytest.mark.stack3471


class TestBinaryCatalog:
    def open_app(self, page):
        requests = []
        responses = []
        console_errors = []
        page.on("request", lambda request: requests.append(request.url))
        page.on(
            "response",
            lambda response: responses.append({
                "url": response.url,
                "status": response.status,
                "size": len(response.body()) if response.request.resource_type in
                        ("fetch", "xhr") else 0,
                "encoding": response.headers.get("content-encoding") or "",
            }),
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error" else None,
        )
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.view === 'solar' && s.frame > 0", timeout=45000)
        return requests, responses, console_errors

    def test_uses_v2_binary_and_skips_full_json(self, page):
        requests, responses, console_errors = self.open_app(page)

        binary = [url for url in requests if "format=v2" in url]
        assert binary, f"no v2 binary request; requests: {requests}"
        # The fallback requests the full JSON catalog exactly as `/api/objects`
        # (no query string). Solar JSON uses `?scale=solar` and is expected.
        assert f"{URL}/api/objects" not in requests, (
            "the full JSON catalog was requested instead of the binary path"
        )
        assert not console_errors, console_errors

        binary_response = next(
            row for row in responses if "format=v2" in row["url"]
        )
        assert binary_response["status"] == 200
        # 3 471 real objects are ~320 KB; the 100k stress catalog is ~13 MB.
        assert 0 < binary_response["size"] < 20 * 1024 * 1024
        # nginx gzips application/octet-stream, so the catalog never travels raw.
        assert binary_response["encoding"] == "gzip", binary_response

        measures = page.evaluate(
            "() => performance.getEntriesByType('measure')"
            ".filter(m => m.name.startsWith('astroverse:')).map(m => ({name: m.name, duration: m.duration}))"
        )
        names = {measure["name"] for measure in measures}
        assert "astroverse:binary-parse" in names, measures
        assert "astroverse:catalog-load" in names, measures

    def test_binary_ids_and_names_reach_the_list(self, page):
        self.open_app(page)
        # Earth is solar JSON, Proxima Cen is a local binary row: both must be
        # present with the exact names the catalog uses.
        assert page.locator(".objectName", has_text="Земля").count() >= 1
        switch_view(page, "local")
        rows = page.locator(".objectName")
        assert any(
            "Proxima Cen" in rows.nth(i).text_content()
            for i in range(rows.count())
        )

    def test_select_binary_object_opens_card(self, page):
        self.open_app(page)
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)
        switch_view(page, "local")

        # The list is virtualized, so narrow it down through search first.
        # "Proxima Cen b" also contains "Proxima Cen", hence the exact match.
        page.locator(".searchBox input").fill("Proxima Cen")
        row = wait_row(page, "Proxima Cen")
        row.click(no_wait_after=True)
        page.locator(".infoPanel").wait_for(state="visible", timeout=5000)
        assert page.locator(".infoPanel h1").text_content() == "Proxima Cen"
        wait_state(
            page, "s && s.followObject?.id === 'proxima_cen'", timeout=5000
        )
        # Card details are fetched lazily for binary rows; wait for a
        # description to appear without breaking the scene.
        page.locator(".mainDesc").wait_for(state="visible", timeout=10000)
        assert page.locator(".mainDesc").text_content().strip()

    def test_search_uses_compact_server_endpoint(self, page):
        requests, _, _ = self.open_app(page)
        page.locator(".searchBox input").fill("планета")
        page.wait_for_timeout(700)
        assert any("/api/search?q=" in url for url in requests), requests
        assert page.locator(".objectRow").count() > 1

    def test_no_resource_growth_on_view_switching(self, page):
        self.open_app(page)
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)

        def cycle():
            for view in ("local", "galaxy", "solar"):
                switch_view(page, view)
                # LOD creates L2 meshes lazily under a per-frame budget and
                # crossfades them over several frames. Sampling on a fixed
                # timeout used to catch the first cycle mid-build, so the second
                # cycle legitimately created the rest and the test failed.
                wait_lod_settled(page)

        # Warm up: the first local visit builds lazy textures/materials.
        cycle()
        before = page.evaluate("() => window.__astroverseSmoke().resources")
        cycle()
        after = page.evaluate("() => window.__astroverseSmoke().resources")

        # Shared caches may legitimately add a few entries on first use, but a
        # second full cycle must not keep growing them.
        for key in ("geometries", "materials", "textures"):
            assert after[key] <= before[key] + 1, (
                f"{key} grew after a second view cycle: {before} -> {after}"
            )
        assert after["rendererGeometries"] <= before["rendererGeometries"] + 1
        assert after["rendererTextures"] <= before["rendererTextures"] + 1


class TestBinaryTransport:
    """The catalog must travel gzipped: 13 MB raw on 100k is too much on wire."""

    def fetch(self, url):
        request = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.headers, response.read()

    def test_v2_is_gzipped_and_intact(self):
        headers, raw = self.fetch(f"{URL}/api/objects?format=v2")
        assert headers.get("Content-Encoding") == "gzip"
        # gzip_vary on: proxies must not serve a compressed body to a client
        # that did not ask for it.
        assert "Accept-Encoding" in (headers.get("Vary") or "")

        decoded = gzip.decompress(raw)
        assert decoded[:4] == b"ASTV", decoded[:16]
        # Compression must actually shrink the payload (roughly 4x for 3 471).
        assert len(raw) * 2 < len(decoded), (len(raw), len(decoded))

    def test_v2_is_not_compressed_when_not_requested(self):
        request = urllib.request.Request(
            f"{URL}/api/objects?format=v2", headers={"Accept-Encoding": "identity"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            assert response.headers.get("Content-Encoding") is None
            # A raw response keeps Content-Length, unlike the chunked gzip one.
            assert int(response.headers["Content-Length"]) > 0
