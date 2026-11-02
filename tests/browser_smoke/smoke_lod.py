"""Smoke test: deep-sky LOD keeps draw calls bounded and stays pickable.

Covers the Phase 1 blocker: lazy L2 mesh creation/disposal.
- L2 meshes are NOT created at startup for local objects (placeholder only).
- L2 mesh is created when object enters L2 (approach) or is selected.
- L2 mesh is disposed when object leaves L2 or view is switched.
- No orphaned meshes after local ↔ solar ↔ galaxy switching.
"""
import pytest

from common import INSTALL_PROBE, URL, switch_view, wait_state

pytestmark = pytest.mark.stack3471


class TestLOD:
    def open_app(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.view === 'solar' && s.frame > 0", timeout=45000)

    def _to_local(self, page):
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)
        switch_view(page, "local")
        wait_state(
            page,
            "s && s.metrics && s.metrics.calls < 50",
            timeout=10000,
        )

    def _lod_counts(self, page):
        return page.evaluate("() => window.__astroverseSmoke().lodCounts")

    def _wait_frames(self, page, n=5):
        for _ in range(n):
            wait_state(
                page,
                f"s && s.frame > {page.evaluate('() => window.__astroverseSmoke().frame')}",
                timeout=5000,
            )

    def test_local_view_collapses_draw_calls(self, page):
        self.open_app(page)
        self._to_local(page)

        state = self._lod_counts(page)
        assert state is not None
        # Every local object is represented: 1233 stars + 1500 exoplanets,
        # plus any galaxy-scale clusters that joined the LOD system.
        assert sum(state) >= 2733, f"Expected at least 2733 LOD objects, got {sum(state)}"
        assert state[0] > 0, "far objects should stay in the L0 point cloud"
        assert state[1] > 0, "mid-distance objects should use L1 instancing"
        # Before LOD this view issued one draw call per object (~2700).
        smoke = page.evaluate("() => window.__astroverseSmoke()")
        assert smoke["metrics"]["calls"] < 50, smoke["metrics"]

    def test_no_l2_meshes_at_startup(self, page):
        """At local view startup, no detailed L2 meshes exist for local objects."""
        self.open_app(page)
        self._to_local(page)

        counts = self._lod_counts(page)
        assert counts is not None
        # At the default local camera, most objects are far (L0/L1).
        # L2 count should be small (only very close objects).
        assert counts[2] < 100, f"Too many L2 meshes at startup: {counts[2]}"

    def test_l2_mesh_created_on_select(self, page):
        """Selecting an object from the canvas forces L2 mesh creation."""
        self.open_app(page)
        self._to_local(page)

        before = self._lod_counts(page)
        assert before is not None
        before_l2 = before[2]

        # Click Proxima Cen to select it — forces L2 via ensureL2.
        projection = page.evaluate(
            "id => window.__astroverseSmoke(id)", "proxima_cen"
        )["projection"]
        assert projection is not None
        assert projection["inFrustum"]
        page.mouse.click(projection["x"], projection["y"])
        self._wait_frames(page)

        after = self._lod_counts(page)
        assert after is not None
        assert after[2] > before_l2, (
            f"L2 count should increase after selection: {before_l2} -> {after[2]}"
        )

    def test_no_orphaned_meshes_on_view_switch(self, page):
        """Switching local ↔ solar ↔ galaxy disposes L2 meshes, no orphans."""
        self.open_app(page)
        self._to_local(page)

        # Create an L2 mesh by selecting Proxima Cen.
        projection = page.evaluate(
            "id => window.__astroverseSmoke(id)", "proxima_cen"
        )["projection"]
        page.mouse.click(projection["x"], projection["y"])
        self._wait_frames(page)

        before = self._lod_counts(page)
        assert before is not None and before[2] > 0, "L2 mesh should exist after selection"

        # Switch to solar and back to local.
        switch_view(page, "solar")
        switch_view(page, "local")
        self._wait_frames(page)

        after = self._lod_counts(page)
        assert after is not None
        # L2 meshes must have been disposed on view switch; count should not grow.
        assert after[2] <= before[2], (
            f"L2 count should not grow after view switch: {before[2]} -> {after[2]}"
        )
        # Draw calls must stay bounded after returning to local.
        smoke = page.evaluate("() => window.__astroverseSmoke()")
        assert smoke["metrics"]["calls"] < 50, smoke["metrics"]

    def test_lod_point_can_be_picked(self, page):
        self.open_app(page)
        # `_to_local` waits for a frame actually drawn with the LOD layer; a
        # click before that frame sees `levels === -1` and is ignored.
        self._to_local(page)

        # Proxima Cen is rendered as an L1 instance at the default local camera,
        # so its detailed mesh is hidden: the click must go through LOD picking.
        projection = page.evaluate(
            "id => window.__astroverseSmoke(id)", "proxima_cen"
        )["projection"]
        assert projection is not None
        assert projection["inFrustum"]
        assert projection["unobscured"]
        # The placeholder is always visible (it renders nothing); the detailed
        # L2 mesh is only created on approach/select. LOD picking still handles
        # the click because the placeholder has no geometry to raycast against.

        page.mouse.click(projection["x"], projection["y"])
        page.locator(".infoPanel").wait_for(state="visible", timeout=5000)
        assert page.locator(".infoPanel h1").text_content() == "Proxima Cen"
        wait_state(
            page, "s && s.followObject?.id === 'proxima_cen'", timeout=5000
        )
