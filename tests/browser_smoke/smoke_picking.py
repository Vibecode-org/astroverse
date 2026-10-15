"""Smoke test: Earth focus, follow toggle, close panel, canvas picking."""
import math
import re
import pytest


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


class TestPicking:
    def select_earth(self, page):
        names = page.locator(".objectName").filter(has_text=re.compile(r"^Земля$"))
        row = page.locator(".objectRow").filter(has=names)
        row.wait_for(state="visible", timeout=5000)
        assert row.count() == 1
        row.click()
        # Wait for panel
        panel = page.locator(".infoPanel")
        panel.wait_for(state="visible", timeout=5000)
        panel.locator("h1").wait_for(state="visible", timeout=5000)
        assert panel.locator("h1").text_content() == "Земля"
        assert panel.locator(".eyebrow").text_content() == "PLANET"
        page.wait_for_function(
            "s => s && s.followCamera && s.followObject?.id === 'earth' && "
            "Math.hypot(...s.target.map((v, i) => v - s.earthWorld[i])) < 1e-5",
            timeout=10000,
        )
        assert page.locator(".followToggle input").is_checked()
        # Wait for frames
        for _ in range(8):
            page.wait_for_function(
                f"s => s && s.frame > {page.evaluate('() => window.__astroverseSmoke().frame')}",
                timeout=5000,
            )

    def close_panel(self, page):
        page.locator(".infoPanel .close").click()
        page.locator(".infoPanel").wait_for(state="detached", timeout=5000)
        assert not page.locator(".followToggle input").is_checked()
        page.wait_for_function(
            "s => s && !s.followCamera && s.followObject === null",
            timeout=5000,
        )

    def test_earth_focus_follow_toggle_and_close(self, page):
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
            lambda el: el.get_attribute("aria-pressed") == "true", timeout=5000
        )

        self.select_earth(page)
        focused = page.evaluate("() => window.__astroverseSmoke()")
        assert math.dist(focused["target"], focused["earthWorld"]) < 1e-5

        # Toggle follow off
        toggle = page.locator(".followToggle input")
        toggle.uncheck()
        assert not toggle.is_checked()
        page.wait_for_function("s => s && !s.followCamera", timeout=5000)

        # Toggle follow on
        toggle.check()
        assert toggle.is_checked()
        page.wait_for_function("s => s && s.followCamera && s.followObject?.id === 'earth'", timeout=5000)
        for _ in range(8):
            page.wait_for_function(
                f"s => s && s.frame > {page.evaluate('() => window.__astroverseSmoke().frame')}",
                timeout=5000,
            )

        before = page.evaluate("() => window.__astroverseSmoke()")
        # Resume
        page.get_by_role("button", name="Продолжить", exact=True).click()
        page.get_by_role("button", name="Пауза", exact=True).wait_for(
            lambda el: el.get_attribute("aria-pressed") == "false", timeout=5000
        )
        page.wait_for_function(
            f"s => s && Math.hypot(...s.earthWorld.map((v, i) => v - {before['earthWorld']}[i])) > 0.02 && "
            f"Math.hypot(...s.camera.map((v, i) => v - {before['camera']}[i])) > 0.01",
            timeout=10000,
        )
        after = page.evaluate("() => window.__astroverseSmoke()")
        assert after["followCamera"]
        assert math.dist(after["target"], after["earthWorld"]) < 1e-3
        earth_delta = [a - b for a, b in zip(after["earthWorld"], before["earthWorld"])]
        camera_delta = [a - b for a, b in zip(after["camera"], before["camera"])]
        assert math.dist(camera_delta, earth_delta) < 1e-3

        # Pause and close
        page.get_by_role("button", name="Пауза", exact=True).click()
        page.get_by_role("button", name="Продолжить", exact=True).wait_for(
            lambda el: el.get_attribute("aria-pressed") == "true", timeout=5000
        )
        self.close_panel(page)

    def test_canvas_picking_returns_catalog_object(self, page):
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
            lambda el: el.get_attribute("aria-pressed") == "true", timeout=5000
        )

        self.select_earth(page)
        self.close_panel(page)
        for _ in range(8):
            page.wait_for_function(
                f"s => s && s.frame > {page.evaluate('() => window.__astroverseSmoke().frame')}",
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
        page.wait_for_function("s => s && s.followCamera && s.followObject?.id === 'earth'", timeout=5000)
        selected = page.evaluate("() => window.__astroverseSmoke().followObject")
        assert selected["kind"] == "planet"
        assert not selected["isObject3D"]