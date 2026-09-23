"""Build a catalog from an independent snapshot and optional live NASA sources."""

import argparse
import copy
import json
import logging
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if __package__:
    from .catalog import catalog_path, load_catalog, validate_catalog, write_catalog
else:
    from catalog import catalog_path, load_catalog, validate_catalog, write_catalog

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = DATA_DIR / "catalog_config.json"
PARSEC_TO_LIGHT_YEARS = 3.261563777
NASA_ARCHIVE = "NASA Exoplanet Archive"
JPL_SBDB = "NASA JPL SBDB"
LOG = logging.getLogger(__name__)


class SourceError(RuntimeError):
    """A required upstream source could not be read or normalized."""


class JsonClient:
    def __init__(self, settings):
        self.timeout = settings["timeout_seconds"]
        self.retries = settings["retries"]
        self.user_agent = settings["user_agent"]

    def get(self, url, params=None):
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


def number(value):
    """Missing/nonfinite measurements stay unknown; never synthesize physics."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def measurement(value, *, positive=False):
    value = number(value)
    if value is None or value < 0 or (positive and value == 0):
        return None
    return value


def slug(name):
    value = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not value:
        raise SourceError(f"Cannot create an ID for {name!r}")
    return value


def identity_index(seed):
    index = {}
    for item in seed:
        for name in (item["name"], item.get("latin")):
            if name:
                index[(item["kind"], name.casefold())] = item
    return index


def make_object(kind, name, scale, config, identities):
    previous = identities.get((kind, name.casefold()), {})
    item = {"id": previous.get("id", slug(name)), "name": previous.get("name", name),
            "latin": name, "kind": kind, "scale": scale, "facts": []}
    item.update(config["display"][kind])
    # Visual/editorial overrides are not measurements from the new source.
    for field in ("radius", "color", "texture", "rings", "atmosphere"):
        if field in previous:
            item[field] = copy.deepcopy(previous[field])
    return item


def coordinates(row):
    ra, dec = number(row.get("ra")), number(row.get("dec"))
    if ra is not None and not 0 <= ra <= 360:
        raise SourceError(f"Invalid right ascension: {ra}")
    if dec is not None and not -90 <= dec <= 90:
        raise SourceError(f"Invalid declination: {dec}")
    distance = measurement(row.get("sy_dist"))
    return {"ra": (ra / 15) % 24 if ra is not None else None,
            "dec": dec, "distance_ly": distance * PARSEC_TO_LIGHT_YEARS if distance is not None else None}


def fetch_exoplanets(client, config, identities, limit):
    fields = ("pl_name,hostname,ra,dec,sy_dist,pl_rade,pl_bmasse,pl_orbper,"
              "pl_eqt,pl_orbsmax,discoverymethod,disc_year,st_teff,st_mass,st_spectype")
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
        star.update({"source": NASA_ARCHIVE, "source_url": config["sources"]["exoplanets"]["url"],
                     "temperature_k": measurement(row.get("st_teff"), positive=True),
                     "mass_sun": measurement(row.get("st_mass"), positive=True),
                     "spectral_type": row.get("st_spectype"), "description": f"Звезда — хозяин планетной системы {host}."})
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
        planet.update({"parent": star["id"], "source": NASA_ARCHIVE,
                       "source_url": config["sources"]["exoplanets"]["url"],
                       "radius_earth": measurement(row.get("pl_rade"), positive=True),
                       "mass_earth": measurement(row.get("pl_bmasse"), positive=True),
                       "period_days": measurement(row.get("pl_orbper"), positive=True),
                       "temperature_k": measurement(row.get("pl_eqt"), positive=True),
                       "au": measurement(row.get("pl_orbsmax"), positive=True),
                       "description": f"Экзопланета в системе {host}."})
        if row.get("discoverymethod"):
            planet["facts"].append(f"Метод открытия: {row['discoverymethod']}")
        if row.get("disc_year"):
            planet["facts"].append(f"Год открытия: {row['disc_year']}")
        if planet["temperature_k"] is not None:
            planet["facts"].append("Указана равновесная температура, а не измеренная температура поверхности.")
        planets.append(planet)
    return list(stars.values()) + planets


def fetch_small_bodies(client, config, identities, kind, limit):
    source = config["sources"]["asteroids" if kind == "asteroid" else "comets"]
    fields = ["full_name", "pdes", "a", "per", "diameter"]
    payload = client.get(source["url"], {"fields": ",".join(fields), "sb-kind": "a" if kind == "asteroid" else "c",
                                        "sort": "pdes", "limit": limit})
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
        # Named asteroids include an extra provisional designation, e.g.
        # "1 Ceres (A801 AA)"; retain the existing catalog identity "1 Ceres".
        full_name = row["full_name"].strip()
        name = re.sub(r"\s+\([^)]*\)$", "", full_name)
        if re.fullmatch(r"\d+", name):
            name = full_name
        name = re.sub(r"[()]", "", name).strip()
        item = make_object(kind, name, "solar", config, identities)
        diameter = measurement(row["diameter"], positive=True)
        item.update({"parent": "sun", "au": measurement(row["a"], positive=True),
                     "period_days": measurement(row["per"], positive=True),
                     "radius_km": diameter / 2 if diameter is not None else None,
                     "source": JPL_SBDB, "source_url": source["url"], "source_id": str(row["pdes"]),
                     "description": f"{'Астероид' if kind == 'asteroid' else 'Комета'} из базы малых тел NASA JPL SBDB."})
        # Do not opt hundreds of small bodies into synchronous live Horizons requests.
        items.append(item)
    return items


def enrich_wikipedia(items, client, config):
    for item in items:
        # Explicit article titles avoid ambiguous name lookups and unbounded requests.
        title = item.get("wikipedia_title")
        if not title:
            continue
        url = config["sources"]["wikipedia"]["url"] + urllib.parse.quote(title, safe="")
        try:
            response = client.get(url)
            if not isinstance(response, dict) or response.get("type") == "disambiguation":
                raise SourceError("Ambiguous or malformed Wikipedia summary")
            extract = response.get("extract")
            if not isinstance(extract, str) or not extract.strip():
                raise SourceError("Empty Wikipedia summary")
            item["description"] = extract.strip()
            item["description_source"] = url
        except SourceError as exc:
            LOG.warning("Wikipedia enrichment skipped for %s: %s", item["id"], exc)


def load_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        config = json.load(stream)
    http = config["http"]
    if not isinstance(http["retries"], int) or isinstance(http["retries"], bool) or http["retries"] < 0:
        raise ValueError("http.retries must be a nonnegative integer")
    if measurement(http["timeout_seconds"], positive=True) is None:
        raise ValueError("http.timeout_seconds must be positive")
    for name in ("exoplanets", "asteroids", "comets"):
        positive_limit(config["sources"][name]["limit"])
    return config


def positive_limit(value):
    if isinstance(value, bool) or str(value) != str(int(value)) or int(value) <= 0:
        raise ValueError("source limit must be a positive integer")
    return int(value)


def build_enriched_catalog(config_path=DEFAULT_CONFIG, output=None, *, offline=False, wikipedia=False,
                           limits=None, client=None):
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    seed_path = (config_path.parent / config["seed"]).resolve()
    output = Path(output) if output is not None else catalog_path()
    if output.resolve() in (seed_path, config_path):
        raise ValueError("Output must not overwrite the input snapshot or configuration")
    if offline and wikipedia:
        raise ValueError("--offline cannot be combined with --wikipedia")
    seed = load_catalog(seed_path)
    items = copy.deepcopy(seed)
    if not offline:
        client = client or JsonClient(config["http"])
        identities = identity_index(seed)
        limits = limits or {}
        imported = []
        for source in ("exoplanets", "asteroids", "comets"):
            limit = positive_limit(limits.get(source, config["sources"][source]["limit"]))
            LOG.info("Loading %s (limit %s)", source, limit)
            if source == "exoplanets":
                imported.extend(fetch_exoplanets(client, config, identities, limit))
            else:
                imported.extend(fetch_small_bodies(client, config, identities,
                                                   "asteroid" if source == "asteroids" else "comet", limit))
        items = [item for item in items if not (
            (item.get("source") == NASA_ARCHIVE and item["kind"] in {"star", "exoplanet"})
            or item["kind"] in {"asteroid", "comet"})]
        items.extend(imported)
        if wikipedia:
            enrich_wikipedia(items, client, config)
    validate_catalog(items)
    write_catalog(output, items)
    LOG.info("Saved %s objects to %s (%s)", len(items), output, "offline snapshot" if offline else "NASA refreshed")
    return items


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, help="Defaults to ASTROVERSE_CATALOG_PATH or data/objects.json")
    parser.add_argument("--offline", action="store_true", help="Rebuild only from the independent input snapshot")
    parser.add_argument("--wikipedia", action="store_true", help="Refresh descriptions with explicit wikipedia_title")
    for source in ("exoplanets", "asteroids", "comets"):
        parser.add_argument(f"--{source}-limit", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    limits = {source: getattr(args, f"{source}_limit") for source in ("exoplanets", "asteroids", "comets")
              if getattr(args, f"{source}_limit") is not None}
    try:
        build_enriched_catalog(args.config, args.output, offline=args.offline, wikipedia=args.wikipedia, limits=limits)
    except (SourceError, ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(1, f"Catalog build failed; output was not replaced: {exc}\n")


if __name__ == "__main__":
    main()
