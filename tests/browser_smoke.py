"""Diagnostic smoke tests: real Chrome, unittest, synchronous Python Playwright.

Private React fibers are intentionally inspected only from the test page. No
application hooks, npm dependencies, mocked catalog, or injected Three import.
"""

import math
import os
import re
import time
import unittest
from datetime import datetime, timedelta

from playwright.sync_api import expect, sync_playwright


URL = "http://localhost:5173"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TIMEOUT_MS = 10_000
LOAD_TIMEOUT_MS = 45_000

# Rewalk the committed root on every call: keeping a fiber/hook reference would
# read stale state after React swaps its current/alternate trees. Both useRef({})
# and the previous useState({current: {}}) representation have a current wrapper.
INSTALL_PROBE = r"""() => {
    window.__astroverseSmoke = (projectId = null) => {
        const container = document.getElementById('root');
        const key = container && Object.keys(container).find(
            name => name.startsWith('__reactContainer$'));
        const hostRoot = key && container[key];
        const root = hostRoot?.stateNode?.current;
        if (!root) return null;

        const pending = [root];
        const seen = new Set();
        let state = null;
        while (pending.length && !state) {
            const fiber = pending.pop();
            if (!fiber || seen.has(fiber)) continue;
            seen.add(fiber);
            if (fiber.sibling) pending.push(fiber.sibling);
            if (fiber.child) pending.push(fiber.child);
            const hooksSeen = new Set();
            for (let hook = fiber.memoizedState;
                 hook && typeof hook === 'object' && !hooksSeen.has(hook);
                 hook = hook.next) {
                hooksSeen.add(hook);
                let value = hook.memoizedState;
                for (let depth = 0; value && depth < 4; depth++) {
                    if (value.scene?.isScene && value.camera && value.renderer &&
                        value.controls && value.meshes?.get) {
                        state = value;
                        break;
                    }
                    value = value.current;
                }
                if (state) break;
            }
        }
        if (!state) return null;
        const vector = v => v ? [v.x, v.y, v.z] : null;
        const earth = state.meshes.get('earth');
        const earthWorld = earth?.getWorldPosition(earth.position.clone());
        const result = {
            view: state.view,
            visible: {
                system: state.system.visible,
                nearby: state.nearby.visible,
                galaxy: state.galaxy.group.visible,
            },
            camera: vector(state.camera.position),
            target: vector(state.controls.target),
            earth: vector(earth?.position),
            earthWorld: vector(earthWorld),
            followCamera: Boolean(state.followCamera),
            followObject: state.followObject ? {
                id: state.followObject.id,
                kind: state.followObject.kind ?? null,
                isObject3D: Boolean(state.followObject.isObject3D),
            } : null,
            frame: state.renderer.info.render.frame,
            date: document.querySelector('.scaleBadge')?.textContent.trim(),
        };
        if (projectId !== null) {
            const mesh = state.meshes.get(projectId);
            if (!mesh) return {...result, projection: null};
            let visible = true;
            for (let node = mesh; node; node = node.parent) {
                visible = visible && node.visible;
            }
            const ndc = mesh.getWorldPosition(mesh.position.clone()).project(state.camera);
            const canvas = state.renderer.domElement;
            const rect = canvas.getBoundingClientRect();
            const x = rect.left + (ndc.x + 1) * rect.width / 2;
            const y = rect.top + (1 - ndc.y) * rect.height / 2;
            const inFrustum = Math.abs(ndc.x) < 1 && Math.abs(ndc.y) < 1 &&
                              ndc.z > -1 && ndc.z < 1;
            result.projection = {
                x, y, z: ndc.z, visible, inFrustum,
                unobscured: inFrustum && document.elementFromPoint(x, y) === canvas,
            };
        }
        return result;
    };
}"""


def parse_badge_date(text):
    """Parse ru-RU numeric date/time independently of the host Python locale."""
    match = re.search(
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})\D+(\d{1,2}):(\d{2}):(\d{2})", text
    )
    if not match:
        raise AssertionError(f"Unexpected Russian .scaleBadge date: {text!r}")
    day, month, year, hour, minute, second = map(int, match.groups())
    return datetime(year, month, day, hour, minute, second)


class BrowserSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.addClassCleanup(cls.playwright.stop)
        cls.browser = cls.playwright.chromium.launch(
            executable_path=CHROME,
            headless=os.environ.get("SMOKE_HEADED") != "1",
        )
        cls.addClassCleanup(cls.browser.close)

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
            timezone_id="UTC",  # Day jumps must not cross local DST boundaries.
            device_scale_factor=1,
        )
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(TIMEOUT_MS)
        self.page.set_default_navigation_timeout(LOAD_TIMEOUT_MS)
        self.page_errors = []
        self.page.on("pageerror", lambda error: self.page_errors.append(str(error)))
        self.addCleanup(self.assert_no_page_errors)
        self.page.goto(URL, wait_until="domcontentloaded")
        expect(self.page.locator(".topmeta")).to_contain_text(
            "3471 ТЕЛ", timeout=LOAD_TIMEOUT_MS
        )
        expect(self.page.locator(".viewport canvas")).to_be_visible(
            timeout=LOAD_TIMEOUT_MS
        )
        self.page.evaluate(INSTALL_PROBE)
        self.wait_state(
            "s.view === 'solar' && s.earth !== null && s.frame > 0",
            timeout=LOAD_TIMEOUT_MS,
        )

    def assert_no_page_errors(self):
        self.assertEqual(self.page_errors, [], "Uncaught browser pageerror")

    def snapshot(self, project_id=None):
        state = self.page.evaluate("id => window.__astroverseSmoke(id)", project_id)
        self.assertIsNotNone(state, "Scene not found in current React hook state")
        return state

    def wait_state(self, condition, arg=None, timeout=TIMEOUT_MS):
        try:
            handle = self.page.wait_for_function(
                "arg => { const s = window.__astroverseSmoke(); "
                f"return s && ({condition}); }}",
                arg=arg,
                timeout=timeout,
            )
            handle.dispose()
        except Exception as error:
            raise AssertionError(
                f"Scene condition timed out/failed: {condition}\n"
                f"Last snapshot: {self.snapshot()}\nPage errors: {self.page_errors}"
            ) from error

    def wait_frames(self, count=3):
        self.wait_state("s.frame >= arg", self.snapshot()["frame"] + count)

    def pause(self):
        self.page.get_by_role("button", name="Пауза", exact=True).click()
        expect(self.page.get_by_role("button", name="Продолжить", exact=True)).to_have_attribute(
            "aria-pressed", "true"
        )
        self.wait_frames()

    def resume(self):
        self.page.get_by_role("button", name="Продолжить", exact=True).click()
        expect(self.page.get_by_role("button", name="Пауза", exact=True)).to_have_attribute(
            "aria-pressed", "false"
        )

    def assert_vector_close(self, actual, expected, tolerance=1e-5):
        self.assertIsNotNone(actual)
        self.assertIsNotNone(expected)
        self.assertLessEqual(math.dist(actual, expected), tolerance, (actual, expected))

    def select_earth(self):
        names = self.page.locator(".objectName").filter(has_text=re.compile(r"^Земля$"))
        row = self.page.locator(".objectRow").filter(has=names)
        expect(row).to_have_count(1)
        row.click()
        self.assert_earth_panel()
        self.wait_state(
            "s.followCamera && s.followObject?.id === 'earth' && "
            "Math.hypot(...s.target.map((v, i) => v - s.earthWorld[i])) < 1e-5"
        )
        expect(self.page.locator(".followToggle input")).to_be_checked()
        self.wait_frames(8)

    def assert_earth_panel(self):
        panel = self.page.locator(".infoPanel")
        expect(panel).to_be_visible()
        expect(panel.locator("h1")).to_have_text("Земля")
        # Catalog kind, not a Three Mesh/type or an undefined selected.kind.
        expect(panel.locator(".eyebrow")).to_have_text("PLANET")

    def close_panel(self):
        self.page.locator(".infoPanel .close").click()
        expect(self.page.locator(".infoPanel")).to_have_count(0)
        expect(self.page.locator(".followToggle input")).not_to_be_checked()
        self.wait_state("!s.followCamera && s.followObject === null")

    def test_01_catalog_canvas_without_pageerror(self):
        state = self.snapshot()
        self.assertEqual(state["view"], "solar")
        self.assertEqual(state["visible"], {"system": True, "nearby": False, "galaxy": False})
        self.wait_frames()
        self.assert_no_page_errors()

    def test_02_views_move_camera_and_render_while_paused(self):
        self.pause()
        date = self.snapshot()["date"]
        for view, label, camera in (
            ("local", "Окрестности Солнца", [0, 35, 70]),
            ("galaxy", "Млечный Путь", [0, 220, 350]),
            ("solar", "Солнечная система", [0, 65, 120]),
        ):
            with self.subTest(view=view):
                before = self.snapshot()
                self.page.locator(".viewControls").get_by_role("button", name=label).click()
                self.wait_state(
                    "s.view === arg.view && s.visible.system === (arg.view === 'solar') && "
                    "s.visible.nearby === (arg.view === 'local') && "
                    "s.visible.galaxy === (arg.view === 'galaxy') && "
                    "Math.hypot(...s.camera.map((v, i) => v - arg.camera[i])) < 1e-3",
                    {"view": view, "camera": camera},
                )
                self.wait_frames()
                after = self.snapshot()
                self.assertGreater(math.dist(before["camera"], after["camera"]), 1)
                self.assertGreater(after["frame"], before["frame"])
                self.assertEqual(after["date"], date)

    def test_03_date_jumps_pause_resume_and_speed(self):
        self.pause()
        initial = self.snapshot()
        initial_date = parse_badge_date(initial["date"])
        offset = 0
        for step in (1, 1, 1, -1, -1, -1):
            before = self.snapshot()
            offset += step
            self.page.get_by_role(
                "button", name="+1 день" if step > 0 else "-1 день", exact=True
            ).click()
            self.wait_state(
                "s.date !== arg.date && "
                "Math.hypot(...s.earth.map((v, i) => v - arg.earth[i])) > 1e-4",
                before,
            )
            self.assertEqual(
                parse_badge_date(self.snapshot()["date"]),
                initial_date + timedelta(days=offset),
            )
        self.assert_vector_close(self.snapshot()["earth"], initial["earth"])

        fixed = self.snapshot()
        # An observation interval is intentional: a single equal sample does not
        # establish that the clock remains paused while rendering continues.
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            self.page.wait_for_timeout(100)
            state = self.snapshot()
            self.assertEqual(parse_badge_date(state["date"]), parse_badge_date(fixed["date"]))
            self.assert_vector_close(state["earth"], fixed["earth"])
        self.assertGreater(self.snapshot()["frame"], fixed["frame"])

        chip = self.page.locator(".speedChip")
        expect(chip).to_have_text("Скорость: ×1")
        for button, speed in (("×1.5", "1.5"), ("×1.5", "2.25"), ("÷2", "1.125")):
            self.page.get_by_role("button", name=button, exact=True).click()
            expect(chip).to_have_text(f"Скорость: ×{speed}")
        self.resume()
        self.wait_state(
            "s.date !== arg.date && "
            "Math.hypot(...s.earth.map((v, i) => v - arg.earth[i])) > 1e-3",
            fixed,
        )
        self.assertGreater(parse_badge_date(self.snapshot()["date"]), parse_badge_date(fixed["date"]))

    def test_04_earth_focus_follow_toggle_and_close(self):
        self.pause()
        self.select_earth()
        focused = self.snapshot()
        self.assert_vector_close(focused["target"], focused["earthWorld"])
        toggle = self.page.locator(".followToggle input")
        toggle.uncheck()
        expect(toggle).not_to_be_checked()
        self.wait_state("!s.followCamera")
        toggle.check()
        expect(toggle).to_be_checked()
        self.wait_state("s.followCamera && s.followObject?.id === 'earth'")
        self.wait_frames(8)
        before = self.snapshot()
        self.resume()
        self.wait_state(
            "Math.hypot(...s.earthWorld.map((v, i) => v - arg.earthWorld[i])) > 0.02 && "
            "Math.hypot(...s.camera.map((v, i) => v - arg.camera[i])) > 0.01",
            before,
        )
        after = self.snapshot()
        self.assertTrue(after["followCamera"])
        self.assert_vector_close(after["target"], after["earthWorld"], 1e-3)
        earth_delta = [a - b for a, b in zip(after["earthWorld"], before["earthWorld"])]
        camera_delta = [a - b for a, b in zip(after["camera"], before["camera"])]
        self.assert_vector_close(camera_delta, earth_delta, 1e-3)
        self.pause()
        self.close_panel()

    def test_05_canvas_picking_returns_catalog_object(self):
        self.pause()
        self.select_earth()
        self.close_panel()
        self.wait_frames(8)
        state = self.snapshot("earth")
        self.assertEqual(state["view"], "solar")
        projection = state["projection"]
        self.assertIsNotNone(projection)
        self.assertTrue(projection["visible"], projection)
        self.assertTrue(projection["inFrustum"], projection)
        self.assertTrue(projection["unobscured"], f"Earth is covered by UI: {projection}")
        # Real pointer events exercise canvas raycasting; do not invoke a React
        # handler, force a locator click through an overlay, or set selection.
        self.page.mouse.click(projection["x"], projection["y"])
        self.assert_earth_panel()
        self.wait_state("s.followCamera && s.followObject?.id === 'earth'")
        selected = self.snapshot()["followObject"]
        self.assertEqual(selected["kind"], "planet")
        self.assertFalse(selected["isObject3D"], selected)
        self.assert_no_page_errors()


if __name__ == "__main__":
    unittest.main(verbosity=2)
