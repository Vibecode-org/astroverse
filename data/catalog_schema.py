"""Catalog schema, identity/parent validation and default path; no codecs."""

import math
import os
import re
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
POSITIVE_FIELDS = frozenset({"period_days", "radius_km", "radius_earth", "moon_distance_km"})
SIGNED_FIELDS = frozenset({"ra", "dec", "galactic_l", "galactic_b", "gx", "gy", "gz"})
# Presentation fields are read straight off the object by the Three.js frontend, where a
# wrong type throws inside the scene build and leaves a permanently blank canvas.
LIST_FIELDS = frozenset({"facts", "missions"})
STRING_FIELDS = frozenset({"description", "structure", "composition", "spectral_type"})
RING_FIELDS = ("inner", "outer")
# Only the real CSS hex lengths: 3/4/6/8 digits. A bare {3,8} would also admit
# 5- and 7-digit values, which parse in JS but are not valid colors.
COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def catalog_path() -> Path:
    """Resolve the environment override on each call, otherwise use the module default."""
    value = os.environ.get("ASTROVERSE_CATALOG_PATH", "")
    if not value.strip():
        return DEFAULT_CATALOG_PATH
    return Path(value)


def _finite_number(value) -> bool:
    # bool is an int subclass, but is not a physical measurement.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _hex_color(value) -> bool:
    # A named colour or url(...) payload here throws from canvas.addColorStop.
    return isinstance(value, str) and COLOR_PATTERN.match(value) is not None


def validate_catalog(items) -> list:
    """Validate without modifying items and return the same list; raise ValueError.

    Optional physical measurements may be null; gravity and escape_velocity also
    accept formatted display strings. The display radius, when supplied, must always
    be positive. Presentation fields must match the shapes the frontend renders.
    Parent IDs form an acyclic graph within this catalog.
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

        if item.get("color") is not None and not _hex_color(item["color"]):
            raise ValueError(f"{label}.color must be a hex string like #ffb74d or null")
        if item.get("tilt") is not None and not _finite_number(item["tilt"]):
            raise ValueError(f"{label}.tilt must be a finite number or null")
        rings = item.get("rings")
        if rings is not None:
            if not isinstance(rings, dict):
                raise ValueError(f"{label}.rings must be an object with inner and outer or null")
            for field in RING_FIELDS:
                edge = rings.get(field)
                if not _finite_number(edge) or edge <= 0:
                    raise ValueError(f"{label}.rings.{field} must be a finite positive number")
        for field in LIST_FIELDS:
            value = item.get(field)
            if value is not None and (not isinstance(value, list)
                                      or not all(isinstance(entry, str) for entry in value)):
                raise ValueError(f"{label}.{field} must be a list of strings or null")
        for field in STRING_FIELDS:
            value = item.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{label}.{field} must be a string or null")

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
