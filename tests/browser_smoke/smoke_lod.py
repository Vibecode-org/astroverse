"""Smoke test: deep-sky LOD keeps draw calls bounded and stays pickable."""
from common import INSTALL_PROBE, URL, wait_state


class TestLOD:
    def open_app(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.view === 'solar' && s.frame > 0", timeout=45000)

    def test_local_view_collapses_draw_calls(self, page):
        self.open_app(page)
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)

        page.locator(".viewControls").get_by_role("button", name="Окрестности Солнца").click(
            no_wait_after=True
        )
        # `view` flips one frame before the renderer uses it; wait for a frame
        # that was actually drawn with the LOD layer.
        wait_state(
            page,
            "s && s.view === 'local' && s.metrics && s.metrics.calls < 100",
            timeout=10000,
        )

        state = page.evaluate("() => window.__astroverseSmoke()")
        counts = state["lodCounts"]
        assert counts is not None
        # Every local object is represented: 1233 stars + 1500 exoplanets.
        assert sum(counts) == 2733
        assert counts[0] > 0, "far objects should stay in the L0 point cloud"
        assert counts[1] > 0, "mid-distance objects should use L1 instancing"
        # Before LOD this view issued one draw call per object (~2700).
        assert state["metrics"]["calls"] < 100, state["metrics"]

    def test_lod_point_can_be_picked(self, page):
        self.open_app(page)
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)

        page.locator(".viewControls").get_by_role("button", name="Окрестности Солнца").click(
            no_wait_after=True
        )
        wait_state(page, "s && s.view === 'local' && s.frame > 0", timeout=10000)

        # Proxima Cen is rendered as an L1 instance at the default local camera,
        # so its detailed mesh is hidden: the click must go through LOD picking.
        projection = page.evaluate(
            "id => window.__astroverseSmoke(id)", "proxima_cen"
        )["projection"]
        assert projection is not None
        assert projection["inFrustum"]
        assert projection["unobscured"]
        assert not projection["visible"]

        page.mouse.click(projection["x"], projection["y"])
        page.locator(".infoPanel").wait_for(state="visible", timeout=5000)
        assert page.locator(".infoPanel h1").text_content() == "Proxima Cen"
        wait_state(
            page, "s && s.followObject?.id === 'proxima_cen'", timeout=5000
        )
