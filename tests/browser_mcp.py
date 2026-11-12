"""Browser regressions through the globally installed Chrome DevTools MCP.

Run: python3 tests/browser_mcp.py --catalog 3471 --report /tmp/astroverse-mcp.json
Requires the Docker stack and chrome-devtools-mcp on PATH. Never silently skips
an unreachable/wrong catalog. Does not import Playwright or modify scene state.
"""

import argparse
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import tempfile
import time

from browser_smoke.common import INSTALL_PROBE, VIEW_LABELS


# Detached TextureLoader images do not appear in document.images. Track their
# real completion (including errors) before taking a GPU-resource baseline.
TRACK_IMAGES = r"""
window.__imageLoads = {pending:0, completed:0};
const imageSrc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
Object.defineProperty(HTMLImageElement.prototype, 'src', {
    ...imageSrc,
    set(value) {
        window.__imageLoads.pending++;
        const done = () => {
            this.removeEventListener('load', done);
            this.removeEventListener('error', done);
            window.__imageLoads.pending--;
            window.__imageLoads.completed++;
        };
        this.addEventListener('load', done);
        this.addEventListener('error', done);
        imageSrc.set.call(this, value);
    },
});
"""


class MCP:
    def __init__(self, slow=False, browser_url=None):
        self.slow = slow
        self.browser_url = browser_url
        self.page_id = 1

    def __enter__(self):
        command = shutil.which("chrome-devtools-mcp")
        if command is None:
            raise RuntimeError("Install chrome-devtools-mcp before running this regression suite")
        self.errors = tempfile.TemporaryFile(mode="w+")
        browser_args = ['--browser-url='+self.browser_url] if self.browser_url else ["--headless", "--isolated",
            "--viewport=1440x1000", "--chrome-arg=--use-angle=swiftshader",
            "--chrome-arg=--enable-unsafe-swiftshader"]
        self.process = subprocess.Popen([
            command, "--no-usage-statistics", "--no-performance-crux", *browser_args,
        ], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, bufsize=0)
        self.buffer = b""
        self.sequence = 0
        try:
            self.request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "astroverse-regression", "version": "1"}})
            self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self.call("list_pages")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.process.stdout.close()
        self.errors.close()

    def send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        self.process.stdin.flush()

    def request(self, method, params):
        self.sequence += 1
        self.send({"jsonrpc": "2.0", "id": self.sequence, "method": method, "params": params})
        deadline = time.monotonic() + 60
        while True:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                message = json.loads(line)
                if message.get("id") == self.sequence:
                    if "error" in message:
                        raise RuntimeError(message["error"])
                    return message["result"]
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError(f"MCP request timed out: {method}")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                self.errors.seek(0)
                raise RuntimeError("MCP exited: " + self.errors.read()[-2000:])
            self.buffer += chunk

    def call(self, name, **arguments):
        # Chrome DevTools MCP 1.12 requires pageId for page-scoped tools.
        if name not in ("list_pages", "new_page"):
            arguments.setdefault("pageId", self.page_id)
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(item.get("text", "") for item in result.get("content", []))
        if result.get("isError"):
            raise RuntimeError(f"{name}: {text}")
        return text

    def evaluate(self, function):
        text = self.call("evaluate_script", function=function, waitForStableDom=False)
        match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
        if not match:
            raise RuntimeError("Missing JSON from evaluate_script: " + text[:500])
        return None if match[1].strip() == "undefined" else json.loads(match[1])

    def wait(self, condition):
        return self.evaluate("""async () => {
            const deadline = performance.now() + 45000;
            while (performance.now() < deadline) {
                const s = window.__astroverseSmoke?.();
                if (CONDITION) return s || true;
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            throw new Error('Regression condition timed out: ' + LABEL + '\\n' + JSON.stringify({
                query: document.querySelector('#object-search')?.value,
                view: window.__astroverseSmoke?.()?.view,
                list: document.querySelector('.list')?.textContent.slice(0, 500),
                errors: window.__regressionErrors
            }));
        }""".replace("CONDITION", condition).replace("LABEL", json.dumps(condition)))

    def uid(self, label, role="button"):
        snapshot = self.call("take_snapshot")
        matches = []
        for line in snapshot.splitlines():
            if f' {role} "' in line and label in line:
                matches.append(line)
        if matches:
            line = min(matches, key=lambda value: len(re.search(role + r' "([^"]*)"', value)[1]))
            return re.search(r"uid=([^\s]+)", line)[1]
        raise AssertionError(f"No {role} {label!r} in snapshot:\n{snapshot[:4000]}")

    def settled(self):
        return self.evaluate("""async () => {
            let previous='', stable=0, lastFrame=-1;
            const deadline=performance.now()+45000;
            while (performance.now()<deadline) {
                const s=window.__astroverseSmoke();
                const key=JSON.stringify([s.view,s.lodCounts,s.resources]);
                if(s.frame!==lastFrame){ stable=key===previous?stable+1:0; previous=key; lastFrame=s.frame; }
                if(stable>=5) return s;
                await new Promise(resolve=>setTimeout(resolve,100));
            }
            throw new Error('LOD/resources failed to settle');
        }""")

    def click(self, label, role="button"):
        uid = self.uid(label, role)
        if self.slow:
            # SwiftShader can take seconds per 100k frame; a real mouse click
            # waits for a frame ACK. Dispatch the same DOM click via MCP.
            self.call("evaluate_script", function="element => { element.click(); return true; }",
                      args=[uid], waitForStableDom=False)
        else:
            self.call("click", uid=uid)

    def search(self, query):
        uid = self.uid("Поиск объектов", "textbox")
        if query and not self.slow:
            self.call("fill", uid=uid, value=query)
        else:
            # Dispatch the native input event: empty fill and OS-specific
            # select-all shortcuts are unreliable in headless macOS Chrome.
            self.evaluate("""() => {
                const input=document.querySelector('#object-search');
                Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,VALUE);
                input.dispatchEvent(new Event('input',{bubbles:true}));
                return input.value;
            }""".replace("VALUE", json.dumps(query)))


def run(catalog, report_path=None):
    report = {"catalog": catalog, "complete": False, "checks": []}

    def passed(label):
        report["checks"].append(label)
        if report_path is not None:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print("PASS", label, flush=True)

    with MCP(slow=catalog == 100000) as mcp:
        mcp.call("navigate_page", url="http://localhost:5173/?scene=legacy", timeout=45000,
                 initScript=TRACK_IMAGES+"window.__regressionErrors=[];addEventListener('error',e=>window.__regressionErrors.push(e.message));addEventListener('unhandledrejection',e=>window.__regressionErrors.push(String(e.reason)));")
        health = mcp.evaluate("async () => (await fetch('/api/health')).json()")
        assert health["objects"] == catalog, health
        mcp.wait(f"document.querySelector('.topmeta')?.textContent.includes('{catalog}') && document.querySelector('.viewport canvas')")
        mcp.evaluate(INSTALL_PROBE)
        mcp.wait("s && s.frame > 0")
        mcp.click("Пауза")
        passed("catalog, WebGL canvas and rendered frame")
        report["measures_ms"] = mcp.evaluate("""() => Object.fromEntries(
            performance.getEntriesByType('measure').filter(m=>m.name.startsWith('astroverse:'))
                .map(m=>[m.name,m.duration]))""")
        if catalog == 100000:
            assert report["measures_ms"]["astroverse:binary-parse"] < 2000, report["measures_ms"]
            assert report["measures_ms"]["astroverse:catalog-load"] < 8000, report["measures_ms"]

        transport = mcp.evaluate("""async () => {
            const r=await fetch('/api/objects?format=v2'); const b=await r.arrayBuffer();
            const v=new DataView(b);
            const etag=r.headers.get('etag');
            const cached=await fetch('/api/objects?format=v2', {headers:{'If-None-Match':etag},cache:'no-cache'});
            return {status:r.status,encoding:r.headers.get('content-encoding'),version:v.getUint32(4,true),
                count:v.getUint32(8,true),bytes:b.byteLength,revalidation:cached.status};
        }""")
        assert transport["status"] == 200 and transport["version"] == 2 and transport["count"] == catalog, transport
        assert transport["encoding"] == "gzip" and transport["bytes"] < 20 * 1024 * 1024, transport
        assert transport["revalidation"] == 304, transport
        report["transport"] = transport
        passed("binary v2, gzip and ETag revalidation")

        spatial = mcp.evaluate("""async () => {
            const root='/api/spatial/v1';
            const c=await (await fetch(root+'/contract')).json();
            const nr=await fetch(root+'/nearby?scale=local&frame=equatorial&x=0&y=0&z=0&radius=32');
            const n=await nr.json();
            if(nr.status!==200 || !n.sectors.length) throw Error(JSON.stringify(n));
            const url=root+'/sectors/'+encodeURIComponent(n.sectors[0].id)+'?limit=2';
            const p=await fetch(url); const page=await p.json();
            const cached=await fetch(url,{headers:{'If-None-Match':p.headers.get('etag')},cache:'no-cache'});
            const id=page.objects[0].object.id;
            const l=await fetch(root+'/objects/'+encodeURIComponent(id)+'/sector');
            const located=await l.json();
            return {contract:c.version,simulationTime:c.simulation_time_supported,
                sectors:n.sectors.length,objects:page.objects.length,
                positionStatus:page.objects[0].coordinates.status,
                simulationPosition:page.objects[0].coordinates.simulation_position,
                sameSector:located.sector.id===n.sectors[0].id,
                cached:cached.status};
        }""")
        assert spatial["contract"] == "coordinates/1" and spatial["simulationTime"] is False, spatial
        assert 0 < spatial["sectors"] <= 128 and 0 < spatial["objects"] <= 2, spatial
        assert spatial["simulationPosition"] is None and spatial["sameSector"], spatial
        assert spatial["cached"] == 304, spatial
        report["spatial"] = spatial
        passed("spatial snapshot API, bounded page, ID lookup and ETag revalidation")

        if catalog == 3471:
            before = mcp.evaluate("() => window.__astroverseSmoke()")
            mcp.click("+1 день")
            mcp.wait("s && s.date !== " + json.dumps(before["date"]))
            mcp.click("−1 день")
            mcp.wait("s && s.date === " + json.dumps(before["date"]) +
                     " && Math.hypot(...s.earth.map((v,i)=>v-" + json.dumps(before["earth"]) + "[i]))<1e-5")
            passed("paused date jumps and deterministic orbit return")

        for view, label in VIEW_LABELS.items():
            mcp.click(label)
            state = mcp.wait("s && s.view === " + json.dumps(view))
            assert sum(state["visible"].values()) == 1, state["visible"]
        passed("all three scales remain mutually exclusive")

        # A loaded image only acquires a GPU texture when its scale is rendered.
        # Warm every scale after CDN completion; keep the later equality strict.
        report["images_before_warmup"] = mcp.evaluate("() => window.__imageLoads")
        mcp.wait("window.__imageLoads.pending===0")
        for view, label in VIEW_LABELS.items():
            mcp.click(label)
            mcp.wait("s && s.view === " + json.dumps(view))
            mcp.settled()
        report["images_after_warmup"] = mcp.evaluate("() => window.__imageLoads")

        mcp.click(VIEW_LABELS["local"])
        expected_local = 100000 if catalog == 100000 else 2733
        state = mcp.wait("s && s.view==='local' && s.metrics.calls<50 && "
                         "s.lodCounts?.reduce((a,b)=>a+b,0)===" + str(expected_local))
        assert 0 < mcp.evaluate("() => document.querySelectorAll('.objectRow').length") <= 40
        report["local"] = {key: state[key] for key in ("metrics", "lodCounts", "resources")}
        if catalog == 100000:
            assert sum(state["lodCounts"]) == catalog, state["lodCounts"]
            assert state["metrics"]["triangles"] < 6_000_000, state["metrics"]
        passed("LOD draw-call budget and virtualized list")

        baseline = mcp.settled()["resources"]
        for _ in range(2):
            mcp.click(VIEW_LABELS["solar"])
            mcp.wait("s?.view==='solar'")
            mcp.click(VIEW_LABELS["local"])
            mcp.wait("s?.view==='local'")
            resources = mcp.settled()["resources"]
            assert resources == baseline, {"before": baseline, "after": resources}
        passed("no geometry/material/texture growth after scale-switch cycles")

        name = "Звезда 000001" if catalog == 100000 else "Proxima Cen"
        mcp.search(name)
        mcp.wait("[...document.querySelectorAll('.objectName')].some(e=>e.textContent===" + json.dumps(name) + ")")
        mcp.click(name)
        selected = mcp.wait("s?.followObject && document.querySelector('.infoPanel h1')?.textContent===" + json.dumps(name))
        assert selected["followCamera"]
        if catalog == 100000:
            # Synthetic stress rows have facts/source but no description.
            mcp.wait("document.querySelector('.source')?.textContent.includes('synthetic')")
        else:
            mcp.wait("document.querySelector('.mainDesc')?.textContent.trim().length>0")
        mcp.click("Телеметрия"); mcp.click("Факты")
        if catalog == 100000:
            mcp.wait("document.querySelector('.factsList')?.textContent.includes('Синтетический объект')")
        mcp.click("Обзор")
        mcp.click("Следить за объектом", "checkbox")
        mcp.wait("s && !s.followCamera")
        mcp.click("×")
        mcp.wait("!document.querySelector('.infoPanel')")
        passed("search, lazy detail card, tabs, follow toggle and close")

        mcp.search("impossible-object-astroverse-xyz")
        mcp.wait("document.querySelector('.list')?.textContent.includes('Ничего не найдено')")
        mcp.search("")
        mcp.wait("document.querySelectorAll('.objectRow').length>0")
        passed("empty search results and recovery")

        report["runtime_errors"] = mcp.evaluate("() => window.__regressionErrors")
        assert not report["runtime_errors"], report["runtime_errors"]
        report["console"] = mcp.call("list_console_messages", types=["error", "warn"])
        assert not re.search(r"\[error\]", report["console"]), report["console"]
        report["network"] = mcp.call("list_network_requests", resourceTypes=["fetch", "xhr"])
        assert not re.search(r"GET http://localhost:5173/api/objects \[", report["network"]), report["network"]
        report["screenshot"] = str((Path(tempfile.gettempdir()) / f"astroverse-mcp-{catalog}.png").resolve())
        mcp.call("take_screenshot", filePath=report["screenshot"])
        passed("no uncaught browser errors")
    report["complete"] = True
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=int, choices=[3471, 100000], default=3471)
    parser.add_argument("--report", type=Path, default=Path("/tmp/astroverse-mcp.json"))
    args = parser.parse_args()
    result = run(args.catalog, args.report)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("Report:", args.report)
