"""Snapshot-space partitioning and bounded disk queries for the spatial API.

Builds an atomic SQLite artifact from a validated catalog. The reader keeps no
catalog in Python memory. Catalog equatorial and galactic axes stay separate;
source reference systems, origins and epochs are unconfirmed. Neither uses the
compressed Three.js display coordinates. See data.coordinates.
"""

import argparse
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile

from data.catalog import load_catalog, validate_catalog

SCHEMA_VERSION = 2
# Leave headroom for the outward rounding performed by SQLite's float32 R-tree.
MAX_BOUND_LY = 3e38


SCHEMA_SQL = """
                PRAGMA journal_mode=DELETE;
                PRAGMA foreign_keys=ON;
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE sectors (
                    id TEXT PRIMARY KEY, scale TEXT NOT NULL, frame TEXT NOT NULL,
                    min_x REAL, min_y REAL, min_z REAL,
                    max_x REAL, max_y REAL, max_z REAL,
                    object_count INTEGER NOT NULL, system_count INTEGER NOT NULL,
                    depth INTEGER NOT NULL, revision TEXT NOT NULL
                );
                CREATE INDEX sector_frame ON sectors(scale, frame);
                CREATE VIRTUAL TABLE sector_bounds USING rtree(
                    sector_rowid, min_x, max_x, min_y, max_y, min_z, max_z
                );
                CREATE TABLE objects (
                    id TEXT PRIMARY KEY, sector_id TEXT NOT NULL REFERENCES sectors(id),
                    root_id TEXT NOT NULL, payload TEXT NOT NULL,
                    ordinal INTEGER NOT NULL, kind TEXT NOT NULL, scale TEXT NOT NULL,
                    search_blob TEXT NOT NULL
                );
                CREATE INDEX sector_objects ON objects(sector_id, id);
                CREATE INDEX object_order ON objects(ordinal);
                CREATE INDEX object_scale ON objects(scale, ordinal);
                CREATE TABLE representations (name TEXT PRIMARY KEY, data BLOB NOT NULL);
            """

class ResultLimitExceeded(ValueError):
    """A complete spatial result would exceed the caller's budget."""


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def physical_position(obj):
    """Return (frame, x, y, z) in ly, or None if measurements are missing.

    Axis order is the catalog Y-up convention. Source origin/epoch/reference
    system remain unknown; this projection is not a verified body position.
    gx/gy/gz are legacy display positions, never physical measurements.
    """
    distance = obj.get("distance_ly")
    if distance is None:
        return None
    if not _finite_number(distance) or not 0 <= distance <= MAX_BOUND_LY:
        raise ValueError("distance_ly is outside the supported physical range")
    if obj.get("ra") is not None and obj.get("dec") is not None:
        frame = "equatorial"
    elif obj.get("galactic_l") is not None and obj.get("galactic_b") is not None:
        frame = "galactic"
    else:
        return None
    fields = ("ra", "dec") if frame == "equatorial" else ("galactic_l", "galactic_b")
    lon, lat = (obj[field] for field in fields)
    if (not _finite_number(lon) or not _finite_number(lat)
            or not 0 <= lon < (24 if frame == "equatorial" else 360)
            or not -90 <= lat <= 90):
        raise ValueError(f"invalid {frame} angles")
    longitude = math.radians(lon * (15 if frame == "equatorial" else 1))
    latitude = math.radians(lat)
    return (frame, distance * math.cos(latitude) * math.cos(longitude),
            distance * math.sin(latitude),
            distance * math.cos(latitude) * math.sin(longitude))


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def build_sector_index(path, items, *, cell_size_ly=32.0, max_objects=4096,
                       max_depth=16, source_signature=None):
    """Write a deterministic grid with adaptive octree leaves to SQLite.

    A complete parent family is the indivisible partition unit, positioned at
    its root. Oversize families or coincident roots can exceed max_objects;
    max_depth bounds subdivision. Input validation/building still needs the
    full list: replacing that build path is Phase 3.5, not claimed here.
    """
    if not _finite_number(cell_size_ly) or not 0 < cell_size_ly <= MAX_BOUND_LY:
        raise ValueError("cell_size_ly must be finite and positive")
    if type(max_objects) is not int or max_objects < 1:
        raise ValueError("max_objects must be a positive integer")
    if type(max_depth) is not int or not 0 <= max_depth <= 32:
        raise ValueError("max_depth must be an integer in [0, 32]")
    cell_size_ly = float(cell_size_ly)
    if cell_size_ly / (1 << max_depth) == 0:
        raise ValueError("cell_size_ly underflows at max_depth")
    validate_catalog(items)
    from data.coordinates import coordinate_contract, snapshot_coordinates
    # Validate provenance before touching the previous artifact.
    for item in items:
        snapshot_coordinates(item)
    ordinals = {item["id"]: ordinal for ordinal, item in enumerate(items)}
    by_id = {item["id"]: item for item in items}
    root_by_id = {}
    families = {}
    for item in items:
        chain = []
        current = item["id"]
        while current not in root_by_id:
            chain.append(current)
            parent = by_id[current].get("parent")
            if parent is None:
                root_by_id[current] = current
                break
            current = parent
        root = root_by_id[current]
        for member in chain:
            root_by_id[member] = root
        if item["scale"] != by_id[root]["scale"]:
            raise ValueError(f"{item['id']}: cross-scale parent family")
        families.setdefault(root, []).append(item)

    groups = {}
    for root, members in sorted(families.items()):
        obj = by_id[root]
        position = physical_position(obj) if obj["scale"] != "solar" else None
        if obj["scale"] == "solar":
            key = ("solar", "system", None)
        elif position is None:
            key = (obj["scale"], "unlocated", None)
        else:
            frame, *xyz = position
            ratios = [v / cell_size_ly for v in xyz]
            if any(not math.isfinite(v) or abs(v) > 2**52 for v in ratios):
                raise ValueError("cell_size_ly is too small for these coordinates")
            grid = tuple(math.floor(v) for v in ratios)
            key = (obj["scale"], frame, grid)
        groups.setdefault(key, []).append((root, position, members))

    path = Path(path)
    stream = tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                         suffix=".tmp", delete=False)
    temporary = Path(stream.name)
    try:
        stream.close()
        with closing(sqlite3.connect(temporary)) as db:
            db.executescript(SCHEMA_SQL)

            def write_leaf(sector_id, scale, frame, bounds, units, depth):
                if bounds is not None:
                    # Include roots even if grid arithmetic rounded the ideal
                    # boundary inwards by a float64 ULP.
                    bounds = [min(bounds[a], *(u[1][a + 1] for u in units)) for a in range(3)] + [
                        max(bounds[a + 3], *(u[1][a + 1] for u in units)) for a in range(3)]
                    if any(not math.isfinite(v) or abs(v) > MAX_BOUND_LY for v in bounds):
                        raise ValueError("sector bounds exceed the R-tree coordinate range")
                rows = sorted((obj["id"], root, _canonical(obj))
                              for root, _, members in units for obj in members)
                digest = hashlib.sha256()
                # Geometry/contract changes must invalidate the sector too.
                digest.update(_canonical([SCHEMA_VERSION, coordinate_contract(), sector_id, bounds]).encode())
                for _, _, payload in rows:
                    digest.update(b"\n")
                    digest.update(payload.encode("utf-8"))
                inserted = db.execute("INSERT INTO sectors VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                      (sector_id, scale, frame, *(bounds or [None] * 6),
                                       len(rows), len(units), depth, digest.hexdigest()))
                if bounds is not None:
                    db.execute("INSERT INTO sector_bounds VALUES (?,?,?,?,?,?,?)",
                               (inserted.lastrowid, bounds[0], bounds[3], bounds[1],
                                bounds[4], bounds[2], bounds[5]))
                db.executemany("INSERT INTO objects VALUES (?,?,?,?,?,?,?,?)",
                               ((oid, sector_id, root, payload, ordinals[oid],
                                 by_id[oid]["kind"], by_id[oid]["scale"],
                                 "\n".join(str(by_id[oid].get(f) or "") for f in
                                           ("name", "latin", "description", "facts", "mythology", "history")).lower())
                                for oid, root, payload in rows))

            def partition(sector_id, scale, frame, lower, side, units, depth):
                count = sum(len(unit[2]) for unit in units)
                if count <= max_objects or len(units) == 1 or depth >= max_depth:
                    write_leaf(sector_id, scale, frame,
                               [*lower, *(v + side for v in lower)], units, depth)
                    return
                half = side / 2
                middle = [v + half for v in lower]
                children = {}
                for unit in units:
                    octant = sum((unit[1][axis + 1] >= middle[axis]) << axis
                                 for axis in range(3))
                    children.setdefault(octant, []).append(unit)
                for octant, child_units in sorted(children.items()):
                    child_lower = [lower[a] + (half if octant & (1 << a) else 0)
                                   for a in range(3)]
                    partition(f"{sector_id}/{octant}", scale, frame, child_lower,
                              half, child_units, depth + 1)

            for (scale, frame, grid), units in sorted(groups.items()):
                if grid is None:
                    write_leaf(f"{scale}:{frame}", scale, frame, None, units, 0)
                else:
                    sector_id = f"{scale}:{frame}:" + ":".join(map(str, grid))
                    partition(sector_id, scale, frame,
                              [v * cell_size_ly for v in grid], cell_size_ly, units, 0)
            metadata = {"schema_version": SCHEMA_VERSION, "unit": "ly",
                        "cell_size_ly": cell_size_ly, "max_objects": max_objects,
                        "max_depth": max_depth, "object_count": len(items)}
            digest = hashlib.sha256(_canonical([SCHEMA_VERSION, coordinate_contract(),
                                               cell_size_ly, max_objects, max_depth]).encode())
            for item in items:
                digest.update(_canonical(item).encode())
                digest.update(b"\n")
            metadata.update(catalog_revision=digest.hexdigest(), coordinates=coordinate_contract(),
                            source_signature=source_signature)
            # Legacy whole-catalog representations are built in the builder,
            # never materialized as dicts/arrays in the API worker.
            from data.catalog import encode_binary_catalog, encode_binary_catalog_v2
            for name, encoder in (("v1", encode_binary_catalog), ("v2", encode_binary_catalog_v2)):
                db.execute("INSERT INTO representations VALUES (?,?)", (name, encoder(items)))
            db.executemany("INSERT INTO metadata VALUES (?,?)",
                           ((key, json.dumps(value)) for key, value in metadata.items()))
            db.commit()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return metadata


class SectorIndex:
    """Read-only disk index. Fetching a leaf loads only that leaf's metadata.

    R-tree bounds are conservative float32 candidates; the final sphere check
    uses the original float64 bounds from the sectors table.
    """

    def __init__(self, path):
        self.path = Path(path).resolve()
        with self._connect() as db:
            metadata = {row["key"]: json.loads(row["value"])
                        for row in db.execute("SELECT * FROM metadata")}
        if metadata.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported sector schema version")
        self.metadata = metadata

    def _connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro")
        db.row_factory = sqlite3.Row
        return closing(db)

    def sectors(self):
        """Offline manifest/inspection; the future API must paginate this."""
        with self._connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sectors ORDER BY id")]

    def nearby(self, scale, frame, center, radius, *, limit=None):
        """Leaves whose closed bounding box intersects a sphere (ly).

        Unknown-position and solar buckets are intentionally not returned.
        This is sector selection, not per-object visibility/frustum culling.
        """
        if (not isinstance(center, (tuple, list)) or len(center) != 3
                or any(not _finite_number(v) for v in center)
                or not _finite_number(radius) or radius < 0):
            raise ValueError("expected a finite center and nonnegative radius")
        x, y, z = center
        with self._connect() as db:
            # CROSS JOIN fixes loop order: without it SQLite can start with
            # sector_frame and probe the R-tree by rowid for every sector,
            # turning a small neighborhood lookup into a full frame scan.
            rows = db.execute("""SELECT s.* FROM sector_bounds b
                CROSS JOIN sectors s ON s.rowid=b.sector_rowid WHERE s.scale=? AND s.frame=?
                AND b.min_x<=? AND b.max_x>=? AND b.min_y<=? AND b.max_y>=?
                AND b.min_z<=? AND b.max_z>=? ORDER BY s.id""",
                              (scale, frame, x + radius, x - radius, y + radius,
                               y - radius, z + radius, z - radius))
            result = []
            for row in rows:
                delta = [max(row[f"min_{a}"] - v, 0, v - row[f"max_{a}"])
                         for a, v in zip("xyz", center)]
                if math.hypot(*delta) <= radius:
                    result.append(dict(row))
                    if limit is not None and len(result) > limit:
                        raise ResultLimitExceeded("too many sectors; reduce radius")
            return result

    def objects(self, sector_id):
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM sectors WHERE id=?", (sector_id,)).fetchone():
                raise KeyError(sector_id)
            return [json.loads(row["payload"]) for row in db.execute(
                "SELECT payload FROM objects WHERE sector_id=? ORDER BY id", (sector_id,))]

    def locate(self, object_id):
        with self._connect() as db:
            row = db.execute("SELECT sector_id FROM objects WHERE id=?", (object_id,)).fetchone()
            return row["sector_id"] if row else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--cell-size-ly", type=float, default=32.0)
    parser.add_argument("--max-objects", type=int, default=4096)
    args = parser.parse_args()
    if args.source.resolve() == args.destination.resolve():
        parser.error("source and destination must differ")
    if args.destination.suffix != ".sqlite":
        parser.error("destination must have a .sqlite extension")
    metadata = build_sector_index(args.destination, load_catalog(args.source),
                                  cell_size_ly=args.cell_size_ly, max_objects=args.max_objects)
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == "__main__":
    main()
