"""Compatibility Horizons day-start vectors and their existing cache policy.

This render-coordinate endpoint remains separate from requested-time positions/1.
Clock, transport, catalog targets and cache are injected by the application.
"""

import csv
import json
import math
import urllib.parse
import urllib.request

from data.runtime_catalog import DiskCatalog


def fetch_jpl_vector(cmd: str, *, utcnow, urlopen):
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

    with urlopen(req, timeout=10) as resp:
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


def solar_ephemeris_targets(catalog):
    """Read only solar candidates without decoding every catalog object."""
    if isinstance(catalog, DiskCatalog):
        with catalog.snapshot() as index:
            for item in index.select(scale="solar"):
                if item.get("jpl_command"):
                    yield item["id"], item["jpl_command"]
    else:
        for item in catalog:
            if item["scale"] == "solar" and item.get("jpl_command"):
                yield item["id"], item["jpl_command"]


def live_ephemeris(*, utcnow, fetch, targets, cache, failure_ttl):
    """Возвращает реальные текущие координаты планет в пространстве напрямую из NASA"""
    now = utcnow()

    # Кэшируем на 1 час, чтобы не перегружать NASA и приложение летало
    if cache["timestamp"] and (now - cache["timestamp"]).total_seconds() < 3600:
        return {"timestamp": cache["timestamp"].isoformat(), "positions": cache["data"], "source": "NASA JPL Horizons (cached)"}

    failed_at = cache["failed_at"]
    if failed_at and (now - failed_at).total_seconds() < failure_ttl:
        return {
            "timestamp": now.isoformat(),
            "positions": cache["data"],
            "source": "NASA JPL Horizons (unavailable, cached)",
        }

    positions = {}
    for planet_id, cmd in targets():
        try:
            vec = fetch(cmd)
            if vec:
                positions[planet_id] = vec
        except Exception as e:
            print(f"JPL Horizons Error for {planet_id}: {e}")

    if positions:
        cache["timestamp"] = now
        cache["data"] = positions
        cache["failed_at"] = None
    else:
        # Do not hammer an unreachable upstream on every request.
        cache["failed_at"] = now

    return {
        "timestamp": now.isoformat(),
        "positions": cache["data"],
        "source": "NASA JPL Horizons Live Ephemeris"
    }

