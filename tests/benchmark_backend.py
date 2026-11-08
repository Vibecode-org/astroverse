"""Reproducible Linux/Docker builder and running-worker measurements.

python -m tests.benchmark_backend build /app/data/catalog_seed.json
python -m tests.benchmark_backend runtime
No reports/DBs remain on disk. RSS is read from /proc; not Python heap size.
"""

import argparse
import json
from pathlib import Path
import resource
import statistics
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


def rss(pid="self"):
    lines = Path(f"/proc/{pid}/status").read_text().splitlines()
    return {line.split(":")[0]: int(line.split()[1]) for line in lines
            if line.startswith(("VmRSS:", "VmHWM:"))}


def build(source):
    from data.catalog import load_catalog
    from data.sectors import build_sector_index
    before = rss()
    start = time.perf_counter()
    items = load_catalog(source)
    loaded = rss()
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "index.sqlite"
        build_sector_index(target, items)
        return dict(mode="builder", count=len(items), before_kib=before,
                    loaded_kib=loaded, after_kib=rss(), peak_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    seconds=time.perf_counter()-start, sqlite_bytes=target.stat().st_size)


def runtime(base):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def fetch(path, headers=None):
        start = time.perf_counter()
        with opener.open(urllib.request.Request(base + path, headers=headers or {}), timeout=60) as response:
            data = response.read()
            return data, dict(response.headers), (time.perf_counter()-start)*1000
    before = rss("1")
    health = json.loads(fetch("/api/health")[0])
    near = "/api/spatial/v1/nearby?scale=local&frame=equatorial&x=0&y=0&z=0&radius=32"
    nearby = json.loads(fetch(near)[0])
    sid = nearby["sectors"][0]["id"]
    paths = {"nearby": near, "sector_page": "/api/spatial/v1/sectors/" + urllib.parse.quote(sid, safe=""),
             "search": "/api/search?q=a", "legacy_v2": "/api/objects?format=v2",
             "legacy_json": "/api/objects", "solar_json": "/api/objects?scale=solar"}
    measurements = {}
    for name, path in paths.items():
        cold, headers, cold_ms = fetch(path)
        warm_ms = [fetch(path)[2] for _ in range(5)]
        status304 = None
        if "etag" in {k.lower() for k in headers}:
            etag = next(v for k, v in headers.items() if k.lower() == "etag")
            try:
                fetch(path, {"If-None-Match": etag})
            except urllib.error.HTTPError as exc:
                assert exc.code == 304, exc.code
                status304 = exc.code
        measurements[name] = dict(bytes=len(cold), cold_ms=round(cold_ms, 3),
                                  warm_median_ms=round(statistics.median(warm_ms), 3),
                                  warm_max_ms=round(max(warm_ms), 3), conditional_status=status304,
                                  worker_kib=rss("1"))
    return dict(mode="runtime", count=health["objects"], before_kib=before,
                after_kib=rss("1"), nearby_sectors=len(nearby["sectors"]), measurements=measurements)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "runtime"))
    parser.add_argument("source", nargs="?", default="data/catalog_seed.json")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    print(json.dumps(build(args.source) if args.mode == "build" else runtime(args.base), indent=2))
