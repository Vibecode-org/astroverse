"""Smoke test: page loads, canvas renders, no console errors."""
import re
from datetime import datetime, timedelta

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


def parse_badge_date(text):
    """Parse ru-RU numeric date/time independently of the host Python locale."""
    match = re.search(
        r"(\d{1,2})\.(\d{1,2})\.(\d{4})\D+(\d{1,2}):(\d{2}):(\d{2})", text
    )
    if not match:
        raise AssertionError(f"Unexpected Russian .scaleBadge date: {text!r}")
    day, month, year, hour, minute, second = map(int, match.groups())
    return datetime(year, month, day, hour, minute, second)


class TestLoad:
    def test_catalog_canvas_without_pageerror(self, page):
        page.goto(URL, wait_until="domcontentloaded")
        page.locator(".topmeta").wait_for(state="visible", timeout=45000)
        page.locator(".viewport canvas").wait_for(state="visible", timeout=45000)
        page.evaluate(INSTALL_PROBE)
        page.wait_for_function(
            "s => s && s.view === 'solar' && s.earth !== null && s.frame > 0",
            timeout=45000,
        )
        state = page.evaluate("() => window.__astroverseSmoke()")
        assert state["view"] == "solar"
        assert state["visible"] == {"system": True, "nearby": False, "galaxy": False}