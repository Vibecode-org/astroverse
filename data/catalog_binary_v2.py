"""Legacy v2 wire codec: typed arrays plus an interned UTF-8 string table."""

import math
import os
import struct
import sys
import tempfile
from array import array
from pathlib import Path

from .catalog_schema import catalog_path, validate_catalog
from .catalog_binary import (
    BINARY_MAGIC, BINARY_VERSION_V2, FLAG_HAS_PARENT, FLAG_HAS_JET,
    KIND_CODES, _render_position, _color_to_uint32, _little_endian_bytes,
)


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
    if any(index < -1 or index >= count for index in parent_indices):
        raise ValueError("invalid parent index")
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
