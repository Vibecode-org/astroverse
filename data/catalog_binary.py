"""Legacy v1 wire codec and shared render-coordinate/binary primitives.

These are illustrative render positions, never requested-time physical centers.
"""

import math
import os
import struct
import sys
import tempfile
from array import array
from pathlib import Path

from .catalog_schema import _finite_number, catalog_path, validate_catalog


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
        # Version dispatch loads the newer codec only when needed.
        from .catalog_binary_v2 import read_binary_catalog_v2
        return read_binary_catalog_v2(path)
    if version != BINARY_VERSION:
        raise ValueError(f"unsupported binary catalog version: {version}")

    with open(path, "rb") as stream:
        header = stream.read(BINARY_HEADER_SIZE)
    if len(header) < BINARY_HEADER_SIZE:
        raise ValueError("truncated binary catalog header")
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
    if any(index < -1 or index >= count for index in parents):
        raise ValueError("invalid parent index")

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
