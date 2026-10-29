"""Smoke test: date jumps, pause/resume, speed controls."""
import math
import time
from datetime import timedelta

from playwright.sync_api import expect

from common import INSTALL_PROBE, URL, parse_badge_date, wait_state


class TestTime:
    def test_date_jumps_pause_resume_and_speed(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        wait_state(page, "s && s.view === 'solar' && s.earth !== null && s.frame > 0", timeout=45000)

        # Pause
        page.get_by_role("button", name="Пауза", exact=True).click(no_wait_after=True)
        expect(page.get_by_role("button", name="Продолжить", exact=True)).to_have_attribute("aria-pressed", "true")

        initial = page.evaluate("() => window.__astroverseSmoke()")
        initial_date = parse_badge_date(initial["date"])
        offset = 0
        for step in (1, 1, 1, -1, -1, -1):
            before = page.evaluate("() => window.__astroverseSmoke()")
            offset += step
            page.get_by_role(
                "button", name="+1 день" if step > 0 else "−1 день", exact=True
            ).click(no_wait_after=True)
            wait_state(
                page,
                f"s && s.date !== '{before['date']}' && "
                f"Math.hypot(...s.earth.map((v, i) => v - {before['earth']}[i])) > 1e-4",
                timeout=5000,
            )
            assert parse_badge_date(page.evaluate("() => window.__astroverseSmoke().date")) == (
                initial_date + timedelta(days=offset)
            )

        # Verify position returns to initial after forward/back
        assert math.dist(
            page.evaluate("() => window.__astroverseSmoke().earth"), initial["earth"]
        ) < 1e-5

        # Verify clock stays paused while rendering continues
        fixed = page.evaluate("() => window.__astroverseSmoke()")
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            page.wait_for_timeout(100)
            state = page.evaluate("() => window.__astroverseSmoke()")
            assert parse_badge_date(state["date"]) == parse_badge_date(fixed["date"])
            assert math.dist(state["earth"], fixed["earth"]) < 1e-5
        assert page.evaluate("() => window.__astroverseSmoke().frame") > fixed["frame"]

        # Speed controls: ▶▶ increases rate, ◀◀ decreases rate
        chip = page.locator(".speedChip")
        chip.wait_for(state="visible", timeout=5000)
        assert chip.text_content() == "×1"

        # Speed up: ×1 → 1 мин/с → 1 час/с
        page.get_by_role("button", name="Ускорить", exact=True).click(no_wait_after=True)
        expect(chip).to_have_text("×1 мин/с", timeout=5000)
        page.get_by_role("button", name="Ускорить", exact=True).click(no_wait_after=True)
        expect(chip).to_have_text("×1 ч/с", timeout=5000)

        # Slow down: 1 час/с → 1 мин/с → ×1
        page.get_by_role("button", name="Замедлить", exact=True).click(no_wait_after=True)
        expect(chip).to_have_text("×1 мин/с", timeout=5000)
        page.get_by_role("button", name="Замедлить", exact=True).click(no_wait_after=True)
        expect(chip).to_have_text("×1", timeout=5000)

        # Resume and verify time advances
        page.get_by_role("button", name="Продолжить", exact=True).click(no_wait_after=True)
        expect(page.get_by_role("button", name="Пауза", exact=True)).to_have_attribute("aria-pressed", "false")
        wait_state(
            page,
            f"s && s.date !== '{fixed['date']}' && "
            f"Math.hypot(...s.earth.map((v, i) => v - {fixed['earth']}[i])) > 1e-6",
            timeout=10000,
        )
        assert parse_badge_date(page.evaluate("() => window.__astroverseSmoke().date")) > parse_badge_date(fixed["date"])
