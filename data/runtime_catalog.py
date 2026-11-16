"""Disk-backed runtime catalog and transaction-pinned reads across replacement."""

from contextlib import closing, contextmanager, nullcontext
import json
from pathlib import Path
import sqlite3
import re
import struct
import logging
import time

from data.sectors import ResultLimitExceeded, SectorIndex
from data.coordinates import coordinate_contract

LOG = logging.getLogger(__name__)


def _validate_representation(name, size, header, count):
    """Validate complete fixed layout using at most the 172-byte v2 header."""
    version = 1 if name == "v1" else 2
    if len(header) < 20 or header[:12] != struct.pack("<4sII", b"ASTV", version, count):
        raise ValueError(f"missing or incompatible runtime representation: {name}")
    if name == "v1":
        offset = struct.unpack_from("<Q", header, 12)[0]
        if offset != 20 or size != 20 + count * 26:
            raise ValueError("invalid runtime v1 representation layout")
        return
    from data.catalog_binary_v2 import BINARY_V2_SECTIONS
    section_count = len(BINARY_V2_SECTIONS)
    header_size = 20 + section_count * 8
    actual_size, actual_count = struct.unpack_from("<II", header, 12)
    if actual_size != header_size or actual_count != section_count or len(header) != header_size:
        raise ValueError("invalid runtime v2 representation header")
    offsets = struct.unpack_from(f"<{section_count}Q", header, 20)
    widths = (12, 4, 4, 1, 1, 4, 1, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4)
    if offsets[0] != header_size or offsets[-1] > size:
        raise ValueError("invalid runtime v2 representation offsets")
    for index, width in enumerate(widths):
        expected_next = offsets[index] + count * width
        expected_next += -expected_next % 4
        if offsets[index] % 4 or offsets[index + 1] != expected_next:
            raise ValueError("invalid runtime v2 representation sections")


def validate_runtime(path, *, full=False):
    """Validate the read contract without deserializing body payloads.

    Bounded checks read metadata, schema and blob headers. Explicit preparation,
    cold publication and API startup request full SQLite integrity/foreign-key
    checks too; that O(N) file check is logged separately from body processing.
    """
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        metadata = Snapshot(path, db).metadata
        if (metadata.get("coordinates") != coordinate_contract()
                or type(metadata.get("object_count")) is not int
                or not 0 <= metadata["object_count"] <= 2**32 - 1
                or not isinstance(metadata.get("catalog_revision"), str)
                or re.fullmatch(r"[0-9a-f]{64}", metadata["catalog_revision"]) is None):
            raise ValueError("incompatible runtime catalog metadata; explicitly prepare or migrate a verified database")
        required = {
            "objects": {"id", "sector_id", "root_id", "payload", "ordinal", "kind", "scale", "search_blob"},
            "sectors": {"id", "scale", "frame", "min_x", "min_y", "min_z", "max_x", "max_y", "max_z", "object_count", "system_count", "depth", "revision"},
            "sector_bounds": {"sector_rowid", "min_x", "max_x", "min_y", "max_y", "min_z", "max_z"},
            "representations": {"name", "data"},
        }
        for table, columns in required.items():
            actual = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            if not columns <= actual:
                raise ValueError(f"incompatible runtime catalog table: {table}")
        for name in ("v1", "v2"):
            row = db.execute("SELECT length(data),substr(data,1,172) FROM representations WHERE name=?", (name,)).fetchone()
            if row is None:
                raise ValueError(f"missing or incompatible runtime representation: {name}")
            _validate_representation(name, row[0], row[1], metadata["object_count"])
        if full:
            started = time.perf_counter()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("runtime catalog SQLite integrity check failed")
            if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise ValueError("runtime catalog foreign-key check failed")
            LOG.info("SQLite integrity verification: %.6fs, %s bytes (O(N) file checks; no body normalization)",
                     time.perf_counter() - started, path.stat().st_size)
    return metadata


class CatalogUnavailable(RuntimeError):
    """The published artifact cannot be read as a supported snapshot."""


class Snapshot(SectorIndex):
    def __init__(self, path, db):
        self.db = db
        super().__init__(path)

    def _connect(self):
        return nullcontext(self.db)

    def select(self, q=None, kind=None, scale=None, sector=None, after=None, limit=None,
               raw=False, max_bytes=None):
        clauses, args = [], []
        for column, value in (("kind", kind), ("scale", scale), ("sector_id", sector)):
            if value is not None:
                clauses.append(f"{column}=?")
                args.append(value)
        if q:
            clauses.append("? != '' AND instr(search_blob, ?) > 0")
            args.append(q.strip().lower())
            args.append(q.strip().lower())
        if after is not None:
            clauses.append("id>?")
            args.append(after)
        sql = "SELECT payload, length(CAST(payload AS BLOB)) AS payload_bytes FROM objects"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY " + ("id" if sector else "ordinal")
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        total_bytes = 0
        for row in self.db.execute(sql, args):
            total_bytes += row["payload_bytes"]
            if max_bytes is not None and total_bytes > max_bytes:
                raise ResultLimitExceeded("object payload byte budget exceeded; reduce limit")
            yield row[0] if raw else json.loads(row[0])

    def object(self, oid):
        row = self.db.execute("SELECT payload FROM objects WHERE id=?", (oid,)).fetchone()
        return json.loads(row[0]) if row else None

    def sector(self, sid):
        row = self.db.execute("SELECT * FROM sectors WHERE id=?", (sid,)).fetchone()
        return dict(row) if row else None

    def has_more(self, sector_id, after):
        """Check page continuation without reading the next object's payload."""
        return self.db.execute(
            "SELECT 1 FROM objects WHERE sector_id=? AND id>? LIMIT 1",
            (sector_id, after)).fetchone() is not None

    def binary(self, version):
        row = self.db.execute("SELECT rowid FROM representations WHERE name=?", (version,)).fetchone()
        with self.db.blobopen("representations", "data", row[0], readonly=True) as blob:
            while chunk := blob.read(65536):
                yield chunk

    def binary_size(self, version):
        return self.db.execute("SELECT length(data) FROM representations WHERE name=?", (version,)).fetchone()[0]


class DiskCatalog:
    def __init__(self, path):
        self.path = Path(path).resolve()
        # Fail at startup on an obsolete/corrupt artifact.
        validate_runtime(self.path)

    @contextmanager
    def snapshot(self):
        try:
            with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True,
                                         check_same_thread=False)) as db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                try:
                    snapshot = Snapshot(self.path, db)
                except ValueError as exc:
                    raise CatalogUnavailable("Published catalog is unavailable or incompatible") from exc
                yield snapshot
        except sqlite3.Error as exc:
            raise CatalogUnavailable("Published catalog is unavailable or incompatible") from exc

    def __len__(self):
        with self.snapshot() as index:
            return index.metadata["object_count"]

    def __iter__(self):
        with self.snapshot() as index:
            yield from index.select()
