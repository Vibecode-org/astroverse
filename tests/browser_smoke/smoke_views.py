"""Smoke test: view switching moves camera and renders while paused."""
import math
import pytest


class TestViews:
    def test_views_move_camera_and_render_while_paused(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        page.wait_for_function(
            "s => s && s.view === 'solar' && s.earth !== null && s.frame > 0",
            timeout=45000,
        )

        # Pause
        page.get_by_role("button", name="Пауза", exact=True).click()
        page.get_by_role("button", name="Продолжить", exact=True).wait_for(
            state="attached", timeout=5000
        )
        page.get_by_role("button", name="Продолжить", exact=True).wait_for(
            lambda el: el.get_attribute("aria-pressed") == "true", timeout=5000
        )

        date = page.evaluate("() => window.__astroverseSmoke().date")

        for view, label, camera in (
            ("local", "Окрестности Солнца", [0, 35, 70]),
            ("galaxy", "Млечный Путь", [0, 220, 350]),
            ("solar", "Солнечная система", [0, 65, 120]),
        ):
            before = page.evaluate("() => window.__astroverseSmoke()")
            page.locator(".viewControls").get_by_role("button", name=label).click()
            page.wait_for_function(
                f"s => s && s.view === '{view}' && "
                f"s.visible.system === {str(view == 'solar').lower()} && "
                f"s.visible.nearby === {str(view == 'local').lower()} && "
                f"s.visible.galaxy === {str(view == 'galaxy').lower()} && "
                f"Math.hypot(...s.camera.map((v, i) => v - {camera}[i])) < 1e-3",
                timeout=10000,
            )
            # Wait for frames to advance
            page.wait_for_function(
                f"s => s && s.frame > {before['frame']}",
                timeout=10000,
            )
            after = page.evaluate("() => window.__astroverseSmoke()")
            assert math.dist(before["camera"], after["camera"]) > 1
            assert after["frame"] > before["frame"]
            assert after["date"] == date