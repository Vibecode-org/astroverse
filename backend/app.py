import csv
import json
import math
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ROOT = Path(__file__).resolve().parents[1]
# Support `uvicorn app:app` from backend/ both locally and in Docker.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.catalog import catalog_path, load_catalog

DATA_PATH = catalog_path()
# Loaded once: restart the backend after catalog or environment changes.
CATALOG = load_catalog(DATA_PATH)

app = FastAPI(title="Astroverse API", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


EPHEMERIS_CACHE = {
    "timestamp": None,
    "data": {}
}

def fetch_jpl_vector(cmd: str):
    """Запрашивает у NASA JPL вектор (X, Y, Z) в а.е. относительно центра Солнца (@10)"""
    base_url = "https://ssd-api.jpl.nasa.gov/horizons.api"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
def objects(q: str | None = None, kind: str | None = None):
    items = CATALOG
    if q:
        ql = q.lower()
        fields = ("name", "latin", "description", "facts", "mythology", "history")
        items = [
            item for item in items
            if any(ql in str(item.get(field) or "").lower() for field in fields)
        ]
    if kind:
        items = [x for x in items if x["kind"] == kind]
    return items

@app.get("/api/live-ephemeris")
def live_ephemeris():
    """Возвращает реальные текущие координаты планет в пространстве напрямую из NASA"""
    now = datetime.now(timezone.utc)

    # Кэшируем на 1 час, чтобы не перегружать NASA и приложение летало
    if EPHEMERIS_CACHE["timestamp"] and (now - EPHEMERIS_CACHE["timestamp"]).total_seconds() < 3600:
        return {"timestamp": EPHEMERIS_CACHE["timestamp"].isoformat(), "positions": EPHEMERIS_CACHE["data"], "source": "NASA JPL Horizons (cached)"}

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

    return {
        "timestamp": now.isoformat(),
        "positions": EPHEMERIS_CACHE["data"],
        "source": "NASA JPL Horizons Live Ephemeris"
    }
