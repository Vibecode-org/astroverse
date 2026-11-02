"""Shared, standard-library-only catalog contract for producers and the API.

Catalogs are loaded once by the API; restart the backend after replacing a catalog
or changing ASTROVERSE_CATALOG_PATH. Unknown metadata fields are preserved.
"""

import json
import math
import os
import re
import struct
import sys
import tempfile
from array import array
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


# ---------------------------------------------------------------------------
# Binary catalog format (Structure-of-Arrays)
# ---------------------------------------------------------------------------

BINARY_MAGIC = b"ASTV"
BINARY_VERSION = 1
BINARY_VERSION_V2 = 2
# Header: magic(4) version(uint32) count(uint32) offset_arrays(uint64) = 20 bytes.
BINARY_HEADER_FORMAT = "<4sIIQ"
BINARY_HEADER_SIZE = struct.calcsize(BINARY_HEADER_FORMAT)

# Per-object flag bits. Bit 0 means "this object has a parent"; the parent index
# in the SoA arrays is -1 otherwise.
FLAG_HAS_PARENT = 0x01
# Bit 1 is used by black holes that render jets (v2 only; v1 has no such field).
FLAG_HAS_JET = 0x02

KIND_CODES = {
    "star": 0,
    "planet": 1,
    "dwarf_planet": 2,
    "moon": 3,
    "asteroid": 4,
    "comet": 5,
    "black_hole": 6,
    "exoplanet": 7,
    "nebula": 8,
    "cluster": 9,
    "galaxy": 10,
}
KIND_NAMES = {code: name for name, code in KIND_CODES.items()}


def _color_to_uint32(color):
    """Parse a CSS hex color into a packed 0xRRGGBBAA uint32."""
    if not color:
        return 0
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value) + "ff"
    elif len(value) == 4:
        value = "".join(ch * 2 for ch in value)
    elif len(value) == 6:
        value += "ff"
    elif len(value) == 8:
        pass
    else:
        return 0
    try:
        return int(value, 16)
    except ValueError:
        return 0


def _uint32_to_color(value):
    r = (value >> 24) & 0xFF
    g = (value >> 16) & 0xFF
    b = (value >> 8) & 0xFF
    a = value & 0xFF
    if a == 0xFF:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"#{r:02x}{g:02x}{b:02x}{a:02x}"


GALAXY_SCALE = 0.0058
SUN_GALACTIC = (78.0, 1.2, -18.0)


def _equatorial_position(obj):
    # Mirror frontend equatorialXYZ (scale=0.9) so positions are render-ready.
    ra = ((obj.get("ra") or 0) * 15 * math.pi) / 180.0
    dec = ((obj.get("dec") or 0) * math.pi) / 180.0
    dist = max(obj.get("distance_ly") or 4, 0.1)
    scale = 0.9
    r = min(dist, 40) * scale + max(0.0, math.log10(dist / 40.0 + 1.0)) * 18.0
    return (
        r * math.cos(dec) * math.cos(ra),
        r * math.sin(dec),
        r * math.cos(dec) * math.sin(ra),
    )


def _galactic_position(obj):
    # Mirror frontend galacticXYZ so galaxy markers land where the UI puts them.
    if obj.get("gx") is not None:
        return (obj["gx"], obj.get("gy") or 0.0, obj.get("gz") or 0.0)
    l = ((obj.get("galactic_l") or 0) * math.pi) / 180.0
    b = ((obj.get("galactic_b") or 0) * math.pi) / 180.0
    r = (obj.get("distance_ly") or 1000) * GALAXY_SCALE
    return (
        SUN_GALACTIC[0] + r * math.cos(b) * math.cos(l),
        SUN_GALACTIC[1] + r * math.sin(b),
        SUN_GALACTIC[2] + r * math.cos(b) * math.sin(l),
    )


def _render_position(obj):
    """Position in the units of the object's own scale.

    Solar objects are heliocentric AU on +X (the frontend computes its own
    compressed layout), local objects use the equatorial projection, galaxy
    objects use the galactic projection. Previously every solar body was
    placed at ``distance_ly or 4``, i.e. all of them at ~4.35 ly from the Sun.
    """
    scale = obj.get("scale")
    if scale == "galaxy":
        return _galactic_position(obj)
    if scale == "solar":
        for field in ("au", "distance"):
            value = obj.get(field)
            if _finite_number(value):
                return (float(value), 0.0, 0.0)
        return (0.0, 0.0, 0.0)
    return _equatorial_position(obj)


def _little_endian_bytes(values) -> bytes:
    """Serialize an ``array`` as little-endian regardless of the host CPU."""
    if sys.byteorder == "little":
        return values.tobytes()
    swapped = array(values.typecode, values)
    swapped.byteswap()
    return swapped.tobytes()


def encode_binary_catalog(items) -> bytes:
    """Encode a catalog as a versioned little-endian SoA binary blob.

    The caller owns validation: filtered subsets (``?kind=``/``?q=``) are
    deliberately allowed here even though their parent references point outside
    the subset. ``write_binary_catalog`` still validates full catalogs.
    """
    id_to_index = {item["id"]: i for i, item in enumerate(items)}
    n = len(items)

    positions = array("f")
    sizes = array("f")
    colors = array("I")
    kinds = array("B")
    flags = array("B")
    parents = array("i")

    for item in items:
        x, y, z = _render_position(item)
        positions.append(float(x))
        positions.append(float(y))
        positions.append(float(z))
        radius = item.get("radius")
        sizes.append(float(radius) if radius is not None else 0.0)
        colors.append(_color_to_uint32(item.get("color")))
        kinds.append(KIND_CODES.get(item.get("kind"), 255))
        parent = item.get("parent")
        flags.append(FLAG_HAS_PARENT if parent is not None else 0)
        parents.append(id_to_index[parent] if parent in id_to_index else -1)

    header = struct.pack(
        BINARY_HEADER_FORMAT, BINARY_MAGIC, BINARY_VERSION, n, BINARY_HEADER_SIZE,
    )
    return b"".join([
        header,
        _little_endian_bytes(positions),
        _little_endian_bytes(sizes),
        _little_endian_bytes(colors),
        _little_endian_bytes(kinds),
        _little_endian_bytes(flags),
        _little_endian_bytes(parents),
    ])


def write_binary_catalog(path, items) -> None:
    """Validate and atomically write a versioned little-endian SoA binary catalog."""
    validate_catalog(items)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = encode_binary_catalog(items)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def read_binary_catalog(path=None):
    """Parse a v1 or v2 binary catalog into typed arrays (Python lists/arrays).

    ``path`` defaults to the catalog resolved from ``ASTROVERSE_CATALOG_PATH``,
    matching ``load_catalog`` and ``write_catalog``.
    """
    path = Path(path) if path is not None else catalog_path()
    with open(path, "rb") as stream:
        header = stream.read(8)
    if len(header) < 8:
        raise ValueError("truncated binary catalog header")
    magic, version = struct.unpack("<4sI", header)
    if magic != BINARY_MAGIC:
        raise ValueError("invalid magic bytes")
    if version == BINARY_VERSION_V2:
        return read_binary_catalog_v2(path)
    if version != BINARY_VERSION:
        raise ValueError(f"unsupported binary catalog version: {version}")

    with open(path, "rb") as stream:
        header = stream.read(BINARY_HEADER_SIZE)
    magic, version, count, offset = struct.unpack(BINARY_HEADER_FORMAT, header)
    if offset != BINARY_HEADER_SIZE:
        raise ValueError("invalid array offset")
    file_size = os.path.getsize(path)
    expected = BINARY_HEADER_SIZE + count * (3 * 4 + 4 + 4 + 1 + 1 + 4)
    if file_size != expected:
        raise ValueError(f"unexpected binary catalog size: {file_size} != {expected}")

    with open(path, "rb") as stream:
        stream.seek(offset)
        data = stream.read()

    positions = array("f")
    sizes = array("f")
    colors = array("I")
    kinds = array("B")
    flags = array("B")
    parents = array("i")

    off = 0
    positions.frombytes(data[off:off + count * 3 * 4]); off += count * 3 * 4
    sizes.frombytes(data[off:off + count * 4]); off += count * 4
    colors.frombytes(data[off:off + count * 4]); off += count * 4
    kinds.frombytes(data[off:off + count]); off += count
    flags.frombytes(data[off:off + count]); off += count
    parents.frombytes(data[off:off + count * 4]); off += count * 4

    # The file is little-endian; ``array`` reads native order.
    if sys.byteorder != "little":
        for values in (positions, sizes, colors, parents):
            values.byteswap()

    return {
        "version": version,
        "count": count,
        "offset": offset,
        "positions": positions,
        "sizes": sizes,
        "colors": colors,
        "kinds": kinds,
        "flags": flags,
        "parent_indices": parents,
    }


# ---------------------------------------------------------------------------
# Binary catalog format v2
# ---------------------------------------------------------------------------
#
# v1 is kept byte-for-byte unchanged for older clients. v2 is a superset:
#
#   header: magic(4) version(uint32=2) count(uint32) header_size(uint32)
#           section_count(uint32) offsets(uint64[section_count])
#   sections (fixed order, every section except `strings` padded to 4 bytes):
#           positions f32[3n]      sizes f32[n]        colors u32[n]
#           kinds u8[n]            flags u8[n]         parents i32[n]
#           scales u8[n]           radius_km f32[n]    radius_earth f32[n]
#           au f32[n]              period_days f32[n]    temperature_k f32[n]
#           id_offsets u32[n]      id_lengths u32[n]
#           name_offsets u32[n]    name_lengths u32[n]
#           latin_offsets u32[n]   latin_lengths u32[n]
#           strings u8[...]        (UTF-8 table, offsets/lengths are bytes)
#
# Numeric fields that are null in JSON are stored as 0.0. `parent` is stored as
# an index into the same catalog (or -1). `scale` is 0=solar, 1=local,
# 2=galaxy. The v2 reader resolves parent indices back to ids.

SCALE_CODES = {"solar": 0, "local": 1, "galaxy": 2}
SCALE_NAMES = {code: name for name, code in SCALE_CODES.items()}

BINARY_V2_SECTIONS = (
    "positions",
    "sizes",
    "colors",
    "kinds",
    "flags",
    "parents",
    "scales",
    "radius_km",
    "radius_earth",
    "au",
    "period_days",
    "temperature_k",
    "id_offsets",
    "id_lengths",
    "name_offsets",
    "name_lengths",
    "latin_offsets",
    "latin_lengths",
    "strings",
)
# magic(4) version(4) count(4) header_size(4) section_count(4) = 20 bytes.
BINARY_V2_FIXED_HEADER_FORMAT = "<4sIIII"
BINARY_V2_FIXED_HEADER_SIZE = struct.calcsize(BINARY_V2_FIXED_HEADER_FORMAT)


def _f32(value) -> float:
    """Null/non-finite optional measurements become 0.0 (the frontend treats 0 as absent)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value) if math.isfinite(value) else 0.0


def _pad4(data: bytes) -> bytes:
    return data + b"\x00" * ((-len(data)) % 4)



def encode_binary_catalog_v2(items) -> bytes:
    """Encode a catalog as a v2 little-endian SoA blob with a UTF-8 string table.

    Like ``encode_binary_catalog``, filtered subsets are allowed even when their
    parent references point outside the subset.
    """
    id_to_index = {item["id"]: i for i, item in enumerate(items)}
    n = len(items)

    positions = array("f")
    sizes = array("f")
    colors = array("I")
    kinds = array("B")
    flag_bits = array("B")
    parents = array("i")
    scales = array("B")
    radius_km = array("f")
    radius_earth = array("f")
    au = array("f")
    period_days = array("f")
    temperature_k = array("f")
    id_offsets = array("I")
    id_lengths = array("I")
    name_offsets = array("I")
    name_lengths = array("I")
    latin_offsets = array("I")
    latin_lengths = array("I")

    strings = bytearray()
    string_index = {}

    def intern(text):
        if not text:
            return 0, 0
        cached = string_index.get(text)
        if cached is not None:
            return cached
        encoded = text.encode("utf-8")
        offset = len(strings)
        strings.extend(encoded)
        result = (offset, len(encoded))
        string_index[text] = result
        return result

    for item in items:
        x, y, z = _render_position(item)
        positions.append(float(x))
        positions.append(float(y))
        positions.append(float(z))
        sizes.append(_f32(item.get("radius")))
        colors.append(_color_to_uint32(item.get("color")))
        kinds.append(KIND_CODES.get(item.get("kind"), 255))
        flags = FLAG_HAS_PARENT if item.get("parent") is not None else 0
        if item.get("has_jet"):
            flags |= FLAG_HAS_JET
        flag_bits.append(flags)
        parents.append(id_to_index.get(item.get("parent"), -1))
        scales.append(SCALE_CODES.get(item.get("scale"), 255))
        radius_km.append(_f32(item.get("radius_km")))
        radius_earth.append(_f32(item.get("radius_earth")))
        au.append(_f32(item.get("au")))
        period_days.append(_f32(item.get("period_days")))
        temperature_k.append(_f32(item.get("temperature_k")))

        id_offset, id_length = intern(item.get("id") or "")
        name_offset, name_length = intern(item.get("name") or "")
        latin_offset, latin_length = intern(item.get("latin") or "")
        id_offsets.append(id_offset)
        id_lengths.append(id_length)
        name_offsets.append(name_offset)
        name_lengths.append(name_length)
        latin_offsets.append(latin_offset)
        latin_lengths.append(latin_length)

    sections = [
        _little_endian_bytes(positions),
        _little_endian_bytes(sizes),
        _little_endian_bytes(colors),
        _little_endian_bytes(kinds),
        _little_endian_bytes(flag_bits),
        _little_endian_bytes(parents),
        _little_endian_bytes(scales),
        _little_endian_bytes(radius_km),
        _little_endian_bytes(radius_earth),
        _little_endian_bytes(au),
        _little_endian_bytes(period_days),
        _little_endian_bytes(temperature_k),
        _little_endian_bytes(id_offsets),
        _little_endian_bytes(id_lengths),
        _little_endian_bytes(name_offsets),
        _little_endian_bytes(name_lengths),
        _little_endian_bytes(latin_offsets),
        _little_endian_bytes(latin_lengths),
        bytes(strings),
    ]

    section_count = len(BINARY_V2_SECTIONS)
    header_size = BINARY_V2_FIXED_HEADER_SIZE + 8 * section_count
    offsets = []
    cursor = header_size
    body = []
    for index, data in enumerate(sections):
        offsets.append(cursor)
        # `strings` is last: no padding, its length is "rest of file".
        if index != section_count - 1:
            data = _pad4(data)
        body.append(data)
        cursor += len(data)

    header = struct.pack(
        BINARY_V2_FIXED_HEADER_FORMAT,
        BINARY_MAGIC,
        BINARY_VERSION_V2,
        n,
        header_size,
        section_count,
    ) + struct.pack(f"<{section_count}Q", *offsets)
    return b"".join([header, *body])


def write_binary_catalog_v2(path, items) -> None:
    """Validate and atomically write a v2 binary catalog."""
    validate_catalog(items)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = encode_binary_catalog_v2(items)

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _array_from_bytes(typecode, data):
    values = array(typecode)
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def read_binary_catalog_v2(path=None):
    """Parse a v2 binary catalog into typed arrays plus decoded strings.

    Returns the v1-compatible keys (``positions``, ``sizes``, ``colors``,
    ``kinds``, ``flags``, ``parent_indices``) and the v2 additions (``scales``,
    ``radius_km``, ``radius_earth``, ``au``, ``period_days``,
    ``temperature_k``, ``ids``, ``names``, ``latins``, ``parents``).
    """
    path = Path(path) if path is not None else catalog_path()
    data = path.read_bytes()
    if len(data) < BINARY_V2_FIXED_HEADER_SIZE:
        raise ValueError("truncated binary catalog header")
    magic, version, count, header_size, section_count = struct.unpack_from(
        BINARY_V2_FIXED_HEADER_FORMAT, data, 0,
    )
    if magic != BINARY_MAGIC:
        raise ValueError("invalid magic bytes")
    if version != BINARY_VERSION_V2:
        raise ValueError(f"unsupported binary catalog version: {version}")
    if section_count != len(BINARY_V2_SECTIONS):
        raise ValueError(
            f"unexpected v2 section count: {section_count} != {len(BINARY_V2_SECTIONS)}"
        )
    expected_header = BINARY_V2_FIXED_HEADER_SIZE + 8 * section_count
    if header_size != expected_header:
        raise ValueError(f"invalid v2 header size: {header_size} != {expected_header}")
    if len(data) < header_size:
        raise ValueError("truncated v2 section table")
    offsets = struct.unpack_from(f"<{section_count}Q", data, BINARY_V2_FIXED_HEADER_SIZE)
    for index, offset in enumerate(offsets):
        if offset < header_size or offset > len(data):
            raise ValueError(f"invalid v2 section offset for {BINARY_V2_SECTIONS[index]}")
        if index < section_count - 1 and offset % 4:
            raise ValueError(f"unaligned v2 section offset for {BINARY_V2_SECTIONS[index]}")
        if index and offset < offsets[index - 1]:
            raise ValueError("v2 section offsets are not monotonic")

    lengths = {
        "positions": count * 3 * 4,
        "sizes": count * 4,
        "colors": count * 4,
        "kinds": count,
        "flags": count,
        "parents": count * 4,
        "scales": count,
        "radius_km": count * 4,
        "radius_earth": count * 4,
        "au": count * 4,
        "period_days": count * 4,
        "temperature_k": count * 4,
        "id_offsets": count * 4,
        "id_lengths": count * 4,
        "name_offsets": count * 4,
        "name_lengths": count * 4,
        "latin_offsets": count * 4,
        "latin_lengths": count * 4,
    }
    for index, name in enumerate(BINARY_V2_SECTIONS[:-1]):
        if offsets[index] + lengths[name] > len(data):
            raise ValueError(f"truncated v2 section {name}")
        if index + 1 < section_count and offsets[index] + lengths[name] > offsets[index + 1]:
            raise ValueError(f"overlapping v2 section {name}")

    def section(name):
        index = BINARY_V2_SECTIONS.index(name)
        return data[offsets[index]:offsets[index] + lengths[name]]

    strings_offset = offsets[BINARY_V2_SECTIONS.index("strings")]
    strings = data[strings_offset:]
    id_offsets = _array_from_bytes("I", section("id_offsets"))
    id_lengths = _array_from_bytes("I", section("id_lengths"))
    name_offsets = _array_from_bytes("I", section("name_offsets"))
    name_lengths = _array_from_bytes("I", section("name_lengths"))
    latin_offsets = _array_from_bytes("I", section("latin_offsets"))
    latin_lengths = _array_from_bytes("I", section("latin_lengths"))

    def decode(offset_table, length_table):
        result = []
        for offset, length in zip(offset_table, length_table):
            if offset + length > len(strings):
                raise ValueError("v2 string table offset out of range")
            result.append(strings[offset:offset + length].decode("utf-8"))
        return result

    ids = decode(id_offsets, id_lengths)
    names = decode(name_offsets, name_lengths)
    latins = decode(latin_offsets, latin_lengths)
    parent_indices = _array_from_bytes("i", section("parents"))
    parents = [ids[index] if index >= 0 else None for index in parent_indices]

    return {
        "version": version,
        "count": count,
        "offset": header_size,
        "section_offsets": dict(zip(BINARY_V2_SECTIONS, offsets)),
        "positions": _array_from_bytes("f", section("positions")),
        "sizes": _array_from_bytes("f", section("sizes")),
        "colors": _array_from_bytes("I", section("colors")),
        "kinds": _array_from_bytes("B", section("kinds")),
        "flags": _array_from_bytes("B", section("flags")),
        "parent_indices": parent_indices,
        "parents": parents,
        "scales": _array_from_bytes("B", section("scales")),
        "radius_km": _array_from_bytes("f", section("radius_km")),
        "radius_earth": _array_from_bytes("f", section("radius_earth")),
        "au": _array_from_bytes("f", section("au")),
        "period_days": _array_from_bytes("f", section("period_days")),
        "temperature_k": _array_from_bytes("f", section("temperature_k")),
        "ids": ids,
        "names": names,
        "latins": latins,
        "strings": strings,
    }
