import csv
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

ROOT = Path(__file__).resolve().parents[1]
# Support `uvicorn app:app` from backend/ both locally and in Docker.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.catalog import (
    catalog_path, encode_binary_catalog, encode_binary_catalog_v2, load_catalog,
)

DATA_PATH = catalog_path()
# Loaded once: restart the backend after catalog or environment changes.
CATALOG = load_catalog(DATA_PATH)

app = FastAPI(title="Astroverse API", version="0.4.0")

# В обычной схеме frontend и API живут на одном origin (nginx проксирует /api),
# поэтому CORS не нужен. Список разрешённых origin задаётся явно через env:
# ASTROVERSE_CORS_ORIGINS=https://example.org,http://localhost:5173
# Wildcard + credentials не используется: браузеры такой ответ всё равно отвергают.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ASTROVERSE_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )


EPHEMERIS_CACHE = {
    "timestamp": None,
    "data": {},
    # When every JPL request fails, remember the failure for a short while so a
    # single unreachable upstream cannot turn into nine 10-second outbound
    # requests on every incoming call.
    "failed_at": None,
}
EPHEMERIS_FAILURE_TTL_SECONDS = 300

# Serialized binary responses are cached per filter combination: encoding the
# full 100k catalog takes noticeable CPU, and the catalog is immutable for the
# lifetime of the process. Eight entries keep the cache bounded (~21 MB at
# 100k objects); the oldest entry is evicted first.
BINARY_CACHE = OrderedDict()
BINARY_CACHE_MAX = int(os.environ.get("ASTROVERSE_BINARY_CACHE_ENTRIES", "8") or 0)

# Fixed-window rate limits per client IP, disabled with 0. Generous defaults:
# a page load fetches the catalog once, and the smoke suite reloads the page a
# handful of times per run.
RATE_LIMIT_RULES = {
    "/api/objects": (int(os.environ.get("ASTROVERSE_RATE_OBJECTS", "600") or 0), 60.0),
    "/api/search": (int(os.environ.get("ASTROVERSE_RATE_SEARCH", "600") or 0), 60.0),
    "/api/live-ephemeris": (int(os.environ.get("ASTROVERSE_RATE_EPHEMERIS", "20") or 0), 60.0),
}

# The compact search endpoint exists because the binary v2 catalog carries
# ids/names but not descriptions. It returns only the fields the object list
# needs; full metadata is still available from /api/objects/{id}.
SEARCH_LIMIT = int(os.environ.get("ASTROVERSE_SEARCH_LIMIT", "500") or 0)
SEARCH_FIELDS = ("name", "latin", "description", "facts", "mythology", "history")
RATE_LIMIT_STATE = {}

# Searchable text and ids are indexed once per catalog object, lazily. Without
# the index every keystroke lowercases six fields for every object: 600k string
# allocations per query at 100k objects (~80 ms). With it a query is one
# `substring in str` per object (~3 ms at 100k) plus O(1) id lookups.
# Cost is memory: roughly the size of the searchable text itself (~150 B per
# object for the seed catalog). The index is rebuilt when `CATALOG` is replaced
# (tests do that), not when the list is mutated in place.
_CATALOG_INDEX = {"catalog": None, "by_id": {}, "haystacks": []}


def build_catalog_index(items):
    """id → object plus one lowercase searchable blob per object.

    Fields are joined with a newline so a query cannot match across two fields.
    A search box cannot produce a newline, so this keeps the old per-field
    semantics without allocating six strings per object.
    """
    by_id = {}
    haystacks = []
    for item in items:
        by_id.setdefault(item["id"], item)
        haystacks.append("\n".join(str(item.get(f) or "") for f in SEARCH_FIELDS).lower())
    return by_id, haystacks


def catalog_index():
    catalog = CATALOG
    if _CATALOG_INDEX["catalog"] is not catalog:
        by_id, haystacks = build_catalog_index(catalog)
        _CATALOG_INDEX.update(catalog=catalog, by_id=by_id, haystacks=haystacks)
    return _CATALOG_INDEX["by_id"], _CATALOG_INDEX["haystacks"]


def matching_items(query):
    """Objects whose name/latin/description/facts/mythology/history contain `query`."""
    query = query.strip().lower()
    if not query:
        return []
    _, haystacks = catalog_index()
    return [item for item, blob in zip(CATALOG, haystacks) if query in blob]


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    rule = RATE_LIMIT_RULES.get(request.url.path)
    if rule and rule[0] > 0:
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window = RATE_LIMIT_STATE.get((client, request.url.path))
        if window is None or now - window[0] >= rule[1]:
            window = [now, 0]
            RATE_LIMIT_STATE[(client, request.url.path)] = window
        window[1] += 1
        if window[1] > rule[0]:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too Many Requests"},
                headers={"Retry-After": str(int(rule[1]))},
            )
        if len(RATE_LIMIT_STATE) > 4096:
            for key, (started, _) in list(RATE_LIMIT_STATE.items()):
                if now - started >= rule[1]:
                    RATE_LIMIT_STATE.pop(key, None)
    return await call_next(request)


def binary_payload(format_version, q, kind, scale, items) -> bytes:
    """Encode and memoize a binary response for one format/filter combination."""
    key = (format_version, q or "", kind or "", scale or "")
    cached = BINARY_CACHE.get(key)
    if cached is not None:
        BINARY_CACHE.move_to_end(key)
        return cached
    encoder = encode_binary_catalog_v2 if format_version == "v2" else encode_binary_catalog
    data = encoder(items)
    if BINARY_CACHE_MAX > 0:
        BINARY_CACHE[key] = data
        while len(BINARY_CACHE) > BINARY_CACHE_MAX:
            BINARY_CACHE.popitem(last=False)
    return data


def catalog_revision(path=DATA_PATH):
    """Cheap stamp of the catalog file: any rebuild changes size and mtime."""
    try:
        stat = path.stat()
        return f"{stat.st_size}-{stat.st_mtime_ns}"
    except OSError:
        return "0"


CATALOG_REVISION = catalog_revision()
# The catalog cannot change while the process is alive, so clients only need to
# revalidate: a reload costs one conditional request (~300 bytes) instead of
# 13 MB on the 100k catalog.
CACHE_CONTROL = "public, max-age=0, must-revalidate"


def response_etag(version, q=None, kind=None, scale=None):
    # HTTP header values are latin-1: a Cyrillic query must be percent-encoded
    # before it can appear in the validator.
    query = urllib.parse.quote(q or "", safe="")
    return f'"{CATALOG_REVISION}-{version}-{query}-{kind or ""}-{scale or ""}"'


def etag_matches(header, etag):
    """True if an `If-None-Match` header contains `etag` (weak or strong)."""
    if not header:
        return False
    if header.strip() == "*":
        return True
    return any(
        part.strip().removeprefix("W/") == etag for part in header.split(",")
    )


def utcnow():
    """Single clock entry point, patched in tests to exercise cache expiry."""
    return datetime.now(timezone.utc)


def fetch_jpl_vector(cmd: str):
    """Запрашивает у NASA JPL вектор (X, Y, Z) в а.е. относительно центра Солнца (@10)"""
    base_url = "https://ssd-api.jpl.nasa.gov/horizons.api"
    now_str = utcnow().strftime("%Y-%m-%d")

    params = {
        "format": "json",
        "COMMAND": f"'{cmd}'",
        "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS",
        "CENTER": "'@10'",  # Солнце-центрическая система
        "START_TIME": f"'{now_str}'",
        "STOP_TIME": f"'{now_str} 00:01'",
        "STEP_SIZE": "'1d'",
        "CSV_FORMAT": "YES",
        "OUT_UNITS": "AU-D",
        "VEC_TABLE": "2",
        "VEC_CORR": "NONE",
        "REF_PLANE": "ECLIPTIC",
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Astroverse/1.0'})

    with urllib.request.urlopen(req, timeout=10) as resp:
        res = json.loads(resp.read().decode('utf-8'))
        text = res.get("result", "")
        if not isinstance(text, str):
            return None
        _, start, remainder = text.partition("$$SOE")
        block, end, _ = remainder.partition("$$EOE")
        if not start or not end:
            return None
        line = next((line for line in block.splitlines() if line.strip()), None)
        if line is None:
            return None
        try:
            fields = next(csv.reader([line]))
            if len(fields) < 5:
                return None
            x, y, z = (float(value.strip()) for value in fields[2:5])
        except (ValueError, csv.Error):
            return None
        if all(math.isfinite(value) for value in (x, y, z)):
            # Three.js uses Y as the vertical axis; JPL uses Z.
            return {"x": x, "y": z, "z": y}
    return None

@app.get("/api/health")
def health():
    return {"status": "ok", "objects": len(CATALOG)}

@app.get("/api/objects")
def objects(
    request: Request,
    q: str | None = None,
    kind: str | None = None,
    scale: str | None = None,
):
    # Search uses the prebuilt lowercase index instead of lowercasing six
    # fields per object on every request.
    items = matching_items(q) if q else CATALOG
    if kind:
        items = [x for x in items if x["kind"] == kind]
    if scale:
        items = [x for x in items if x["scale"] == scale]

    accept = request.headers.get("accept", "")
    # v2 is explicit: `?format=v2` or the vendor media type. Plain
    # `Accept: application/octet-stream` stays on v1 for older clients.
    format_version = request.query_params.get("format", "").lower()
    wants_v2 = (
        format_version == "v2"
        or "application/vnd.astroverse.catalog.v2" in accept
    )
    wants_binary = wants_v2 or "application/octet-stream" in accept
    version = "v2" if wants_v2 else ("v1" if wants_binary else "json")

    etag = response_etag(version, q, kind, scale)
    headers = {
        "ETag": etag,
        "Cache-Control": CACHE_CONTROL,
        # The same URL answers JSON, v1 or v2 depending on `Accept`, so shared
        # caches must key on it as well.
        "Vary": "Accept",
    }
    if etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)

    if wants_binary:
        # `binary_payload` deliberately skips catalog validation: a filtered
        # subset has parents outside the subset, and validating it would raise
        # "unknown parent" and turn every filtered binary request into a 500.
        data = binary_payload(version, q, kind, scale, items)
        headers.update({
            "X-Object-Count": str(len(items)),
            "X-Catalog-Format": version,
        })
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers=headers,
        )
    return JSONResponse(content=items, headers=headers)


@app.get("/api/search")
def search(q: str = ""):
    """Compact search over the same six fields as `?q=` on `/api/objects`.

    The binary catalog intentionally omits long text, so the frontend asks the
    server when the query is non-empty and maps returned ids back to the
    objects it already has. An empty query returns an empty list.
    """
    results = []
    for item in matching_items(q):
        results.append({
            "id": item["id"],
            "name": item["name"],
            "latin": item.get("latin") or "",
            "kind": item["kind"],
            "scale": item["scale"],
        })
        if SEARCH_LIMIT > 0 and len(results) >= SEARCH_LIMIT:
            break
    return results


@app.get("/api/objects/{object_id}")
def object_by_id(object_id: str):
    """Full metadata for one object (the compact list payload omits long text)."""
    by_id, _ = catalog_index()
    item = by_id.get(object_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Object not found")
    return item


@app.get("/api/live-ephemeris")
def live_ephemeris():
    """Возвращает реальные текущие координаты планет в пространстве напрямую из NASA"""
    now = utcnow()

    # Кэшируем на 1 час, чтобы не перегружать NASA и приложение летало
    if EPHEMERIS_CACHE["timestamp"] and (now - EPHEMERIS_CACHE["timestamp"]).total_seconds() < 3600:
        return {"timestamp": EPHEMERIS_CACHE["timestamp"].isoformat(), "positions": EPHEMERIS_CACHE["data"], "source": "NASA JPL Horizons (cached)"}

    failed_at = EPHEMERIS_CACHE["failed_at"]
    if failed_at and (now - failed_at).total_seconds() < EPHEMERIS_FAILURE_TTL_SECONDS:
        return {
            "timestamp": now.isoformat(),
            "positions": EPHEMERIS_CACHE["data"],
            "source": "NASA JPL Horizons (unavailable, cached)",
        }

    positions = {}
    for item in CATALOG:
        cmd = item.get("jpl_command")
        if item["scale"] != "solar" or not cmd:
            continue
        planet_id = item["id"]
        try:
            vec = fetch_jpl_vector(cmd)
            if vec:
                positions[planet_id] = vec
        except Exception as e:
            print(f"JPL Horizons Error for {planet_id}: {e}")

    if positions:
        EPHEMERIS_CACHE["timestamp"] = now
        EPHEMERIS_CACHE["data"] = positions
        EPHEMERIS_CACHE["failed_at"] = None
    else:
        # Do not hammer an unreachable upstream on every request.
        EPHEMERIS_CACHE["failed_at"] = now

    return {
        "timestamp": now.isoformat(),
        "positions": EPHEMERIS_CACHE["data"],
        "source": "NASA JPL Horizons Live Ephemeris"
    }
