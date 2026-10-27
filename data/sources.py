"""HTTP client with retries and NASA/JPL data fetchers."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

try:
    from data.normalizers import SourceError, coordinates, make_object, measurement
except ImportError:
    from normalizers import SourceError, coordinates, make_object, measurement


class JsonClient:
    """HTTP client with exponential backoff for NASA/JPL APIs."""

    def __init__(self, settings: Dict[str, Any]):
        self.timeout = settings["timeout_seconds"]
        self.retries = settings["retries"]
        self.user_agent = settings["user_agent"]

    def get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                retryable = not isinstance(exc, urllib.error.HTTPError) or exc.code == 429 or exc.code >= 500
                if not retryable or attempt == self.retries:
                    raise SourceError(f"Cannot read {url}: {exc}") from exc
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")


NASA_ARCHIVE = "NASA Exoplanet Archive"
JPL_SBDB = "NASA JPL SBDB"


def fetch_exoplanets(
    client: JsonClient,
    config: Dict[str, Any],
    identities: Dict[tuple, Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """Fetch exoplanets and their host stars from NASA Exoplanet Archive."""
    fields = (
        "pl_name,hostname,ra,dec,sy_dist,pl_rade,pl_bmasse,pl_orbper,"
        "pl_eqt,pl_orbsmax,discoverymethod,disc_year,st_teff,st_mass,st_spectype"
    )
    query = f"select top {limit} {fields} from pscomppars order by sy_dist asc,pl_name asc"
    rows = client.get(config["sources"]["exoplanets"]["url"], {"query": query, "format": "json"})
    if not isinstance(rows, list) or not rows:
        raise SourceError("NASA Exoplanet Archive returned no records")

    stars, planets = {}, []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("pl_name"), str) or not isinstance(row.get("hostname"), str):
            raise SourceError("NASA record is missing pl_name/hostname")
        host, name = row["hostname"].strip(), row["pl_name"].strip()
        if not host or not name:
            raise SourceError("NASA record has an empty name")

        star = make_object("star", host, "local", config, identities)
        star.update(coordinates(row))
        star.update({
            "source": NASA_ARCHIVE,
            "source_url": config["sources"]["exoplanets"]["url"],
            "temperature_k": measurement(row.get("st_teff"), positive=True),
            "mass_sun": measurement(row.get("st_mass"), positive=True),
            "spectral_type": row.get("st_spectype"),
            "description": f"Звезда — хозяин планетной системы {host}.",
        })
        if star["id"] in stars:
            existing = stars[star["id"]]
            if existing["latin"] != host:
                raise SourceError(f"Star ID collision: {host}")
            for key, value in star.items():
                if existing.get(key) is None:
                    existing[key] = value
        else:
            stars[star["id"]] = star

        planet = make_object("exoplanet", name, "local", config, identities)
        planet.update(coordinates(row))
        planet.update({
            "parent": star["id"],
            "source": NASA_ARCHIVE,
            "source_url": config["sources"]["exoplanets"]["url"],
            "radius_earth": measurement(row.get("pl_rade"), positive=True),
            "mass_earth": measurement(row.get("pl_bmasse"), positive=True),
            "period_days": measurement(row.get("pl_orbper"), positive=True),
            "temperature_k": measurement(row.get("pl_eqt"), positive=True),
            "au": measurement(row.get("pl_orbsmax"), positive=True),
            "description": f"Экзопланета в системе {host}.",
        })
        if row.get("discoverymethod"):
            planet["facts"].append(f"Метод открытия: {row['discoverymethod']}")
        if row.get("disc_year"):
            planet["facts"].append(f"Год открытия: {row['disc_year']}")
        if planet["temperature_k"] is not None:
            planet["facts"].append("Указана равновесная температура, а не измеренная температура поверхности.")
        planets.append(planet)

    return list(stars.values()) + planets


def fetch_small_bodies(
    client: JsonClient,
    config: Dict[str, Any],
    identities: Dict[tuple, Dict[str, Any]],
    kind: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """Fetch asteroids or comets from JPL SBDB."""
    import re
    source = config["sources"]["asteroids" if kind == "asteroid" else "comets"]
    fields = ["full_name", "pdes", "a", "per", "diameter"]
    payload = client.get(source["url"], {
        "fields": ",".join(fields),
        "sb-kind": "a" if kind == "asteroid" else "c",
        "sort": "pdes",
        "limit": limit,
    })
    if not isinstance(payload, dict) or not payload.get("data") or not isinstance(payload.get("fields"), list):
        raise SourceError(f"JPL SBDB returned no {kind} records")
    if not set(fields) <= set(payload["fields"]):
        raise SourceError("JPL SBDB response is missing required fields")

    items = []
    for values in payload["data"]:
        if not isinstance(values, list) or len(values) != len(payload["fields"]):
            raise SourceError("Malformed JPL SBDB row")
        row = dict(zip(payload["fields"], values))
        if not isinstance(row["full_name"], str) or not row["full_name"].strip() or not row["pdes"]:
            raise SourceError("JPL SBDB row is missing name/designation")

        full_name = row["full_name"].strip()
        name = re.sub(r"\s+\([^)]*\)$", "", full_name)
        if re.fullmatch(r"\d+", name):
            name = full_name
        name = re.sub(r"[()]", "", name).strip()

        item = make_object(kind, name, "solar", config, identities)
        diameter = measurement(row["diameter"], positive=True)
        item.update({
            "parent": "sun",
            "au": measurement(row["a"], positive=True),
            "period_days": measurement(row["per"], positive=True),
            "radius_km": diameter / 2 if diameter is not None else None,
            "source": JPL_SBDB,
            "source_url": source["url"],
            "source_id": str(row["pdes"]),
            "description": f"{'Астероид' if kind == 'asteroid' else 'Комета'} из базы малых тел NASA JPL SBDB.",
        })
        items.append(item)
    return items
