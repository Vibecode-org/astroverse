"""Pure normalization helpers for catalog building.

No I/O, no network, no side effects — only deterministic transformations.
"""

import math
import re
from typing import Any, Dict, List, Optional


class SourceError(RuntimeError):
    """A required upstream source could not be read or normalized."""


PARSEC_TO_LIGHT_YEARS = 3.261563777


def number(value: Any) -> Optional[float]:
    """Missing/nonfinite measurements stay unknown; never synthesize physics."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def measurement(value: Any, *, positive: bool = False) -> Optional[float]:
    """Like number(), but enforces non-negative (or positive) constraint."""
    value = number(value)
    if value is None or value < 0 or (positive and value == 0):
        return None
    return value


def slug(name: str) -> str:
    """Generate a stable ID from a name."""
    value = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    if not value:
        raise SourceError(f"Cannot create an ID for {name!r}")
    return value


def positive_limit(value: Any) -> int:
    if isinstance(value, bool) or str(value) != str(int(value)) or int(value) <= 0:
        raise ValueError("source limit must be a positive integer")
    return int(value)


def identity_index(seed: List[Dict[str, Any]]) -> Dict[tuple, Dict[str, Any]]:
    """Build lookup index from existing catalog for ID preservation."""
    index = {}
    for item in seed:
        for name in (item["name"], item.get("latin")):
            if name:
                index[(item["kind"], name.casefold())] = item
    return index


def make_object(
    kind: str,
    name: str,
    scale: str,
    config: Dict[str, Any],
    identities: Dict[tuple, Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a base object with display defaults, preserving visual overrides from seed."""
    import copy
    previous = identities.get((kind, name.casefold()), {})
    item = {
        "id": previous.get("id", slug(name)),
        "name": previous.get("name", name),
        "latin": name,
        "kind": kind,
        "scale": scale,
        "facts": [],
    }
    item.update(config["display"][kind])
    # Visual/editorial overrides are not measurements from the new source.
    for field in ("radius", "color", "texture", "rings", "atmosphere"):
        if field in previous:
            item[field] = copy.deepcopy(previous[field])
    return item


def coordinates(row: Dict[str, Any]) -> Dict[str, Any]:
    """Extract and normalize RA/Dec/distance from a NASA row."""
    ra, dec = number(row.get("ra")), number(row.get("dec"))
    if ra is not None and not 0 <= ra <= 360:
        raise SourceError(f"Invalid right ascension: {ra}")
    if dec is not None and not -90 <= dec <= 90:
        raise SourceError(f"Invalid declination: {dec}")
    distance = measurement(row.get("sy_dist"))
    return {
        "ra": (ra / 15) % 24 if ra is not None else None,
        "dec": dec,
        "distance_ly": distance * PARSEC_TO_LIGHT_YEARS if distance is not None else None,
    }