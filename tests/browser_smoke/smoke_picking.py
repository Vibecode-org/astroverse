"""Smoke test: Earth focus, follow toggle, close panel, canvas picking."""
import math
import re

from playwright.sync_api import expect

from common import INSTALL_PROBE, URL, wait_state


class TestPicking:
    def select_earth(self, page):
        names = page.locator(".objectName").filter(has_text=re.compile(r"^Земля$"))
        row = page.locator(".objectRow").filter(has=names)
        row.wait_for(state="visible", timeout=5000)
        assert row.count() == 1
        row.click(no_wait_after=True)
        # Wait for panel
        panel = page.locator(".infoPanel")
        panel.wait_for(state="visible", timeout=5000)
        panel.locator("h1").wait_for(state="visible", timeout=5000)
        assert panel.locator("h1").text_content() == "Земля"
        assert panel.locator(".eyebrow").text_content() == "PLANET"
        wait_state(
            page,
            "s && s.followCamera && s.followObject?.id === 'earth' && "
            "Math.hypot(...s.target.map((v, i) => v - s.earthWorld[i])) < 1e-5",
            timeout=10000,
        )
        assert page.locator(".followToggle input").is_checked()
        # Wait for frames
        for _ in range(8):
            wait_state(
                page,
                f"s && s.frame > {page.evaluate('() => window.__astroverseSmoke().frame')}",
                timeout=5000,
            )

    def close_panel(self, page):
        page.locator(".infoPanel .close").click(no_wait_after=True)
        page.locator(".infoPanel").wait_for(state="detached", timeout=5000)
        assert not page.locator(".followToggle input").is_checked()
        wait_state(page, "s && !s.followCamera && s.followObject === null", timeout=5000)

    def test_earth_focus_follow_toggle_and_close(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.view === 'solar' && s.earth !== null && s.frame > 0", timeout=45000)

        # Pause
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)
        expect(page.get_by_role("button", name="Продолжить", exact=True)).to_have_attribute("aria-pressed", "true")

        self.select_earth(page)
        focused = page.evaluate("() => window.__astroverseSmoke()")
        assert math.dist(focused["target"], focused["earthWorld"]) < 1e-5

        # Toggle follow off
        toggle = page.locator(".followToggle input")
        toggle.uncheck()
        assert not toggle.is_checked()
        wait_state(page, "s && !s.followCamera", timeout=5000)

        # Toggle follow on
        toggle.check()
        assert toggle.is_checked()
        wait_state(page, "s && s.followCamera && s.followObject?.id === 'earth'", timeout=5000)
        for _ in range(8):
            wait_state(
                page,
                f"s && s.frame > {page.evaluate('() => window.__astroverseSmoke().frame')}",
                timeout=5000,
            )

        before = page.evaluate("() => window.__astroverseSmoke()")
        # Resume
        page.get_by_role("button", name="Продолжить", exact=True).click(no_wait_after=True)
        expect(page.get_by_role("button", name="Пауза", exact=True)).to_have_attribute("aria-pressed", "false")
        wait_state(
            page,
            f"s && Math.hypot(...s.earthWorld.map((v, i) => v - {before['earthWorld']}[i])) > 1e-5 && "
            f"Math.hypot(...s.camera.map((v, i) => v - {before['camera']}[i])) > 1e-6",
            timeout=10000,
        )
        after = page.evaluate("() => window.__astroverseSmoke()")
        assert after["followCamera"]
        assert math.dist(after["target"], after["earthWorld"]) < 1e-3
        earth_delta = [a - b for a, b in zip(after["earthWorld"], before["earthWorld"])]
        camera_delta = [a - b for a, b in zip(after["camera"], before["camera"])]
        assert math.dist(camera_delta, earth_delta) < 1e-3

        # Pause and close
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)
        expect(page.get_by_role("button", name="Продолжить", exact=True)).to_have_attribute("aria-pressed", "true")
        self.close_panel(page)

    def test_canvas_picking_returns_catalog_object(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.view === 'solar' && s.earth !== null && s.frame > 0", timeout=45000)

        # Pause
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)
        expect(page.get_by_role("button", name="Продолжить", exact=True)).to_have_attribute("aria-pressed", "true")

        self.select_earth(page)
        self.close_panel(page)
        for _ in range(8):
            wait_state(
                page,
                f"s && s.frame > {page.evaluate('() => window.__astroverseSmoke().frame')}",
                timeout=5000,
            )

        state = page.evaluate("id => window.__astroverseSmoke(id)", "earth")
        assert state["view"] == "solar"
        projection = state["projection"]
        assert projection is not None
        assert projection["visible"]
        assert projection["inFrustum"]
        assert projection["unobscured"], f"Earth is covered by UI: {projection}"

        # Real pointer events exercise canvas raycasting
        page.mouse.click(projection["x"], projection["y"])
        panel = page.locator(".infoPanel")
        panel.wait_for(state="visible", timeout=5000)
        assert panel.locator("h1").text_content() == "Земля"
        wait_state(page, "s && s.followCamera && s.followObject?.id === 'earth'", timeout=5000)
        selected = page.evaluate("() => window.__astroverseSmoke().followObject")
        assert selected["kind"] == "planet"
        assert not selected["isObject3D"]
