"""Public catalog API: validated JSON I/O and compatible v1/v2 codec exports.

Keep existing consumers on this module; implementation lives in schema/codecs.
Unknown metadata fields are preserved. Restart the API after replacing a catalog.
"""

import json
import os
import tempfile
from pathlib import Path

from .catalog_schema import (
    DEFAULT_CATALOG_PATH, SUPPORTED_KINDS, SUPPORTED_SCALES, NONNEGATIVE_FIELDS,
    POSITIVE_FIELDS, SIGNED_FIELDS, LIST_FIELDS, STRING_FIELDS, RING_FIELDS, COLOR_PATTERN,
    catalog_path, _finite_number, _hex_color, validate_catalog,
)
from .catalog_binary import (
    BINARY_MAGIC, BINARY_VERSION, BINARY_VERSION_V2, BINARY_HEADER_FORMAT,
    BINARY_HEADER_SIZE, FLAG_HAS_PARENT, FLAG_HAS_JET, KIND_CODES, KIND_NAMES,
    _color_to_uint32, _uint32_to_color, GALAXY_SCALE, SUN_GALACTIC, _equatorial_position,
    _galactic_position, _render_position, _little_endian_bytes, encode_binary_catalog,
    write_binary_catalog, read_binary_catalog,
)
from .catalog_binary_v2 import (
    SCALE_CODES, SCALE_NAMES, BINARY_V2_SECTIONS, BINARY_V2_FIXED_HEADER_FORMAT,
    BINARY_V2_FIXED_HEADER_SIZE, _f32, _pad4, encode_binary_catalog_v2,
    write_binary_catalog_v2, _array_from_bytes, read_binary_catalog_v2,
)


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
