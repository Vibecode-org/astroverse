"""Disk-backed runtime catalog and transaction-pinned reads across replacement."""

from contextlib import closing, contextmanager, nullcontext
import json
from pathlib import Path
import sqlite3

from data.sectors import ResultLimitExceeded, SectorIndex


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
        SectorIndex(self.path)

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
