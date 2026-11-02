"""Общие константы и helpers для браузерных smoke-тестов."""
import json
import re
import urllib.request
from datetime import datetime

URL = "http://localhost:5173"

# Object counts the two supported stacks serve. `stack3471` / `stack100k`
# markers in conftest.py skip modules that do not match the running stack, so
# one command works against either one.
DEFAULT_OBJECTS = 3471
STRESS_OBJECTS = 100_000

# Button labels live here once: a UI rename touches one dict, not every module.
VIEW_LABELS = {
    "solar": "Солнечная система",
    "local": "Окрестности Солнца",
    "galaxy": "Млечный Путь",
}


def served_object_count(timeout=5):
    """Object count the running stack reports, or 0 when it is unreachable."""
    try:
        with urllib.request.urlopen(f"{URL}/api/health", timeout=timeout) as response:
            return int(json.load(response)["objects"])
    except (OSError, ValueError, KeyError):
        return 0


def switch_view(page, view, timeout=10000):
    """Click a view button and wait until the scene reports that view."""
    page.locator(".viewControls").get_by_role(
        "button", name=VIEW_LABELS[view]
    ).click(no_wait_after=True)
    wait_state(page, f"s && s.view === '{view}'", timeout=timeout)


def wait_lod_settled(page, stable_frames=5, timeout=10000):
    """Wait until the LOD layer stops creating/disposing representations.

    L2 meshes are built lazily under a per-frame budget and crossfaded over
    several frames, so sampling after a fixed sleep is a race: on a slow
    (SwiftShader) run the first sample catches the scene mid-build and the next
    visit legitimately adds more meshes.
    """
    page.wait_for_function(
        """(stableFrames) => {
            const s = window.__astroverseSmoke();
            if (!s || !s.lodCounts) return false;
            const key = s.view + ':' + s.lodCounts.join(',');
            if (window.__lodSettledKey !== key) {
                window.__lodSettledKey = key;
                window.__lodSettledFrames = 0;
                return false;
            }
            window.__lodSettledFrames += 1;
            return window.__lodSettledFrames >= stableFrames;
        }""",
        arg=stable_frames,
        timeout=timeout,
    )


def wait_row(page, name, stable_polls=5, timeout=15000):
    """Wait for exactly one list row showing `name` and return its locator.

    The list is virtualized and re-renders when debounced server search results
    arrive, so a row can appear and be replaced while Playwright is checking it.
    Requiring the row to stay mounted for a few polls removes that race.
    """
    page.wait_for_function(
        """(args) => {
            const [name, stablePolls] = args;
            const rows = [...document.querySelectorAll('.objectRow')];
            const match = rows.filter(
                row => row.querySelector('.objectName')?.textContent.trim() === name
            );
            if (match.length !== 1) {
                window.__rowStable = 0;
                return false;
            }
            const box = match[0].getBoundingClientRect();
            if (!box.width || !box.height) {
                window.__rowStable = 0;
                return false;
            }
            window.__rowStable = (window.__rowStable || 0) + 1;
            return window.__rowStable >= stablePolls;
        }""",
        arg=[name, stable_polls],
        timeout=timeout,
    )
    return page.locator(".objectRow").filter(
        has=page.locator(".objectName", has_text=re.compile(f"^{re.escape(name)}$"))
    ).first


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
        // Resource counters for the leak test. Scene traversal counts unique
        // geometries/materials/textures actually reachable from the scene;
        // renderer.info.memory is the GPU-side view and is reported alongside.
        const textureSlots = [
            'map', 'alphaMap', 'emissiveMap', 'normalMap', 'roughnessMap',
            'metalnessMap', 'aoMap', 'envMap', 'bumpMap', 'displacementMap',
            'specularMap', 'lightMap',
        ];
        const seenGeometry = new Set();
        const seenMaterial = new Set();
        const seenTexture = new Set();
        state.scene.traverse((object) => {
            if (object.geometry) seenGeometry.add(object.geometry);
            const materials = Array.isArray(object.material)
                ? object.material : [object.material];
            for (const material of materials) {
                if (!material) continue;
                seenMaterial.add(material);
                for (const slot of textureSlots) {
                    if (material[slot]) seenTexture.add(material[slot]);
                }
            }
        });
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
            metrics: state.metrics ?? null,
            lodCounts: state.lodCounts ?? null,
            resources: {
                geometries: seenGeometry.size,
                materials: seenMaterial.size,
                textures: seenTexture.size,
                rendererGeometries: state.renderer.info.memory.geometries,
                rendererTextures: state.renderer.info.memory.textures,
            },
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


def wait_state(page, predicate, timeout=10000):
    """Poll `window.__astroverseSmoke()` until the JS predicate using `s` is true."""
    page.wait_for_function(
        "() => { const s = window.__astroverseSmoke(); return Boolean(" + predicate + "); }",
        timeout=timeout,
    )
