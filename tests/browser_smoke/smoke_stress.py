"""Smoke test: 100 000-object stress catalog (Phase 1 acceptance).

The default stack serves 3 471 real objects. This module is marked `stack100k`
and `conftest.py` skips it unless the running stack reports 100 000 objects, so
the same command works against either stack:

    python3 data/gen_catalog_100k.py
    docker compose -f docker-compose.yml -f docker-compose.100k.yml up --build -d
    /tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -m stack100k -v

It checks the properties Phase 1 promises, not a specific frame rate (fps is
measured separately in docs/PERFORMANCE.md with a real GPU):
- the v2 binary catalog loads (no full JSON fallback) within a sane size/time;
- the local view stays under 50 draw calls with bounded triangle count;
- the object list is virtualized (only a viewport of rows is mounted);
- a binary object can be found, selected and opens its card.
"""
import pytest

from common import INSTALL_PROBE, STRESS_OBJECTS, URL, switch_view, wait_row, wait_state

pytestmark = pytest.mark.stack100k

EXPECTED_OBJECTS = STRESS_OBJECTS


class TestStressCatalog:
    def open_app(self, page):
        requests = []
        responses = []
        console_errors = []
        # Headless Chrome renders the 100k catalog with SwiftShader (software
        # rasterisation) at roughly 0.5 fps, so every action wait is measured in
        # seconds. The 10 s default is fine on the 3 471 stack, not here.
        page.set_default_timeout(60_000)
        page.on("request", lambda request: requests.append(request.url))
        page.on(
            "response",
            lambda response: responses.append({
                "url": response.url,
                "status": response.status,
                # nginx gzips application/octet-stream, so the transfer is
                # chunked and Content-Length is absent; Playwright's body() is
                # the decoded catalog, which is what the size budget is about.
                "encoding": response.headers.get("content-encoding") or "",
                "decoded": len(response.body())
                if "format=v2" in response.url else 0,
            }) if response.request.resource_type in ("fetch", "xhr") else None,
        )
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error" else None,
        )
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.wait_for_function(
            "() => document.querySelector('.topmeta')?.textContent.includes('100000')",
            timeout=45000,
        )
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.frame > 0", timeout=45000)
        return requests, responses, console_errors

    def to_local(self, page):
        switch_view(page, "local")
        wait_state(
            page,
            "s && s.metrics && s.metrics.calls < 50",
            timeout=20000,
        )

    def test_loads_v2_binary_without_full_json(self, page):
        requests, responses, console_errors = self.open_app(page)

        assert any("format=v2" in url for url in requests), requests
        # A bare `/api/objects` is the JSON fallback and must not be used on the
        # happy path; `?scale=solar` is the small metadata request.
        assert f"{URL}/api/objects" not in requests, (
            "the full JSON catalog was requested instead of the binary path"
        )
        assert not console_errors, console_errors

        binary = next(row for row in responses if "format=v2" in row["url"])
        assert binary["status"] == 200
        # The catalog itself must stay under 20 MB even uncompressed.
        assert 1 * 1024 * 1024 < binary["decoded"] < 20 * 1024 * 1024, binary
        # nginx compresses application/octet-stream; the wire size is measured
        # separately in smoke_binary::TestBinaryTransport (chunked, no header).
        assert binary["encoding"] == "gzip", binary

        measures = {
            measure["name"]: measure["duration"]
            for measure in page.evaluate(
                "() => performance.getEntriesByType('measure')"
                ".filter(m => m.name.startsWith('astroverse:'))"
                ".map(m => ({name: m.name, duration: m.duration}))"
            )
        }
        assert "astroverse:binary-parse" in measures, measures
        assert "astroverse:catalog-load" in measures, measures
        # Generous ceilings: the numbers are documented in docs/PERFORMANCE.md.
        assert measures["astroverse:binary-parse"] < 2000, measures
        assert measures["astroverse:catalog-load"] < 8000, measures

    def test_local_view_stays_within_draw_call_budget(self, page):
        self.open_app(page)
        self.to_local(page)

        smoke = page.evaluate("() => window.__astroverseSmoke()")
        assert smoke["lodCounts"] is not None
        assert sum(smoke["lodCounts"]) == EXPECTED_OBJECTS, smoke["lodCounts"]
        assert smoke["metrics"]["calls"] < 50, smoke["metrics"]
        # 4.1 M after the L1 sphere reduction (was ~35 M with full L2 meshes).
        assert smoke["metrics"]["triangles"] < 6_000_000, smoke["metrics"]
        assert smoke["metrics"]["points"] >= EXPECTED_OBJECTS, smoke["metrics"]

    def test_object_list_is_virtualized(self, page):
        self.open_app(page)
        self.to_local(page)

        rows = page.locator(".objectRow")
        assert 0 < rows.count() <= 40, f"list is not virtualized: {rows.count()} rows"

        before = rows.first.locator(".objectName").text_content()
        page.locator(".list").evaluate("el => { el.scrollTop = el.scrollHeight; }")
        page.wait_for_function(
            "(previous) => document.querySelector('.objectRow .objectName')?.textContent !== previous",
            arg=before,
            timeout=60000,
        )
        after = page.locator(".objectRow").first.locator(".objectName").text_content()
        assert after != before, "scrolling did not mount a different window of rows"
        assert page.locator(".objectRow").count() <= 40

    def test_select_object_opens_card(self, page):
        self.open_app(page)
        self.to_local(page)

        page.locator(".searchBox input").fill("Звезда 000001")
        row = wait_row(page, "Звезда 000001", timeout=60000)
        # Dispatch the click inside the page: it runs the same React handler,
        # but Playwright's input pipeline waits for a rendering-frame ack, and a
        # single SwiftShader frame of this scene takes ~2.5 s.
        row.evaluate("element => element.click()")

        wait_state(
            page, "s && s.followObject?.id === 'star_000001'", timeout=60000
        )
        assert page.locator(".infoPanel").count() == 1
        assert page.locator(".infoPanel h1").text_content() == "Звезда 000001"
