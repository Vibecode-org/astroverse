"""Smoke test: page loads, canvas renders, no console errors."""
from common import INSTALL_PROBE, URL, wait_state


class TestLoad:
    def test_catalog_canvas_without_pageerror(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.view === 'solar' && s.earth !== null && s.frame > 0", timeout=45000)
        state = page.evaluate("() => window.__astroverseSmoke()")
        assert state["view"] == "solar"
        assert state["visible"] == {"system": True, "nearby": False, "galaxy": False}
