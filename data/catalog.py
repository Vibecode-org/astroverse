"""Shared, standard-library-only catalog contract for producers and the API.

Catalogs are loaded once by the API; restart the backend after replacing a catalog
or changing ASTROVERSE_CATALOG_PATH. Unknown metadata fields are preserved.
"""

import json
import math
import os
import tempfile
from pathlib import Path


DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent / "objects.json"
SUPPORTED_KINDS = frozenset({
    "star", "planet", "dwarf_planet", "moon", "asteroid", "comet",
    "black_hole", "exoplanet", "nebula", "cluster", "galaxy",
})
SUPPORTED_SCALES = frozenset({"solar", "local", "galaxy"})
NONNEGATIVE_FIELDS = frozenset({
    "au", "distance", "distance_ly", "moon_distance", "mass_earth", "mass_sun",
    "temperature_k", "gravity", "escape_velocity",
})
POSITIVE_FIELDS = frozenset({"period_days", "radius_km", "radius_earth"})
SIGNED_FIELDS = frozenset({"ra", "dec", "galactic_l", "galactic_b", "gx", "gy", "gz"})


def catalog_path() -> Path:
    """Resolve the environment override on each call, otherwise use the module default."""
    return Path(os.environ.get("ASTROVERSE_CATALOG_PATH", DEFAULT_CATALOG_PATH))


def _finite_number(value) -> bool:
    # bool is an int subclass, but is not a physical measurement.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_catalog(items) -> list:
    """Validate without modifying items and return the same list; raise ValueError.

    Optional physical measurements may be null; gravity and escape_velocity also
    accept formatted display strings. The display radius, when supplied, must always
    be positive. Parent IDs form an acyclic graph within this catalog.
    """
    if not isinstance(items, list):
        raise ValueError("catalog must be a list of objects")

    by_id = {}
    for index, item in enumerate(items):
        label = f"catalog[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be an object")
        for field in ("id", "name"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{label}.{field} must be a nonempty string")
        label = f"catalog[{index}] ({item['id']})"
        for field, supported in (("kind", SUPPORTED_KINDS), ("scale", SUPPORTED_SCALES)):
            if not isinstance(item.get(field), str) or item[field] not in supported:
                raise ValueError(f"{label}.{field} must be one of {', '.join(sorted(supported))}")
        if item["id"] in by_id:
            raise ValueError(f"{label}: duplicate id {item['id']!r}")
        by_id[item["id"]] = item

        if "radius" in item and (not _finite_number(item["radius"]) or item["radius"] <= 0):
            raise ValueError(f"{label}.radius must be a finite positive number")
        for field in NONNEGATIVE_FIELDS | POSITIVE_FIELDS | SIGNED_FIELDS:
            value = item.get(field)
            if value is None:
                continue
            # These frontend display fields may include formatted values and units.
            if field in {"gravity", "escape_velocity"} and isinstance(value, str):
                continue
            if not _finite_number(value):
                raise ValueError(f"{label}.{field} must be a finite number or null")
            if field in NONNEGATIVE_FIELDS and value < 0:
                raise ValueError(f"{label}.{field} must be nonnegative")
            if field in POSITIVE_FIELDS and value <= 0:
                raise ValueError(f"{label}.{field} must be positive")
            if field == "ra" and not 0 <= value < 24:
                raise ValueError(f"{label}.ra must be in [0, 24) hours")
            if field == "dec" and not -90 <= value <= 90:
                raise ValueError(f"{label}.dec must be in [-90, 90] degrees")

        if "jpl_command" in item:
            command = item["jpl_command"]
            if not isinstance(command, str) or not command.strip():
                raise ValueError(f"{label}.jpl_command must be a nonempty string")
            if item["scale"] != "solar":
                raise ValueError(f"{label}.jpl_command is only allowed for solar objects")

    for object_id, item in by_id.items():
        parent = item.get("parent")
        if parent is None:
            continue
        if not isinstance(parent, str) or parent not in by_id:
            raise ValueError(f"{object_id}: unknown parent {parent!r}")
        if parent == object_id:
            raise ValueError(f"{object_id}: an object cannot be its own parent")

    # Iterative traversal also handles catalogs with very deep parent chains.
    complete = set()
    for object_id in by_id:
        chain = set()
        current = object_id
        while current is not None and current not in complete:
            if current in chain:
                raise ValueError(f"{object_id}: parent cycle involving {current!r}")
            chain.add(current)
            current = by_id[current].get("parent")
        complete.update(chain)
    return items


def load_catalog(path=None) -> list:
    """Read UTF-8 JSON, normalize legacy RA=24 to 0 hours, and validate it."""
    with Path(path if path is not None else catalog_path()).open("r", encoding="utf-8") as stream:
        items = json.load(stream)
    # Older catalogs rounded a few right ascensions to the equivalent 24h endpoint.
    # Normalize only that endpoint in memory; leave the file and strict writer intact.
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and _finite_number(item.get("ra")) and item["ra"] == 24:
                item["ra"] = 0.0
    return validate_catalog(items)


def write_catalog(path, items) -> None:
    """Validate and atomically replace path with UTF-8 JSON in the same directory.

    The destination directory must already exist. Failures leave the previous
    catalog intact and remove any temporary file.
    """
    validate_catalog(items)
    path = Path(path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(items, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
