"""Independent regression probes for publication reuse and malformed artifacts."""

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from backend.prepare_runtime import ensure_runtime
from data.bootstrap_catalog import bootstrap_database, build_bootstrap
from data.incremental_catalog import publish_changes
from data.runtime_catalog import DiskCatalog, validate_runtime


class StartupReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="startup-review-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bootstrap = self.root / "bootstrap.sqlite"
        self.runtime = self.root / "working.sqlite"
        self.source = self.root / "source.json"
        self.source.write_text(
            '[{"id":"sun","name":"Sun","kind":"star","scale":"solar"}]',
            encoding="utf-8")
        build_bootstrap(self.source, self.bootstrap)
        bootstrap_database(self.runtime, bootstrap=self.bootstrap)

    def test_two_bootstrap_builds_have_identical_bytes_and_provenance(self):
        second = self.root / "second-build.sqlite"
        build_bootstrap(self.source, second)
        for suffix in ("", ".sha256", ".manifest.json"):
            self.assertEqual(Path(str(self.bootstrap) + suffix).read_bytes(),
                             Path(str(second) + suffix).read_bytes(), suffix)

    def test_malformed_binary_layout_rejected_without_reading_body_payloads(self):
        with closing(sqlite3.connect(self.runtime)) as db:
            originals = dict(db.execute("SELECT name,data FROM representations"))

        def replace_u32(blob, offset, value):
            return blob[:offset] + struct.pack("<I", value) + blob[offset + 4:]

        def replace_u64(blob, offset, value):
            return blob[:offset] + struct.pack("<Q", value) + blob[offset + 8:]

        corruptions = [
            ("v1", originals["v1"][:16]),
            ("v1", originals["v1"][:-1]),
            ("v1", replace_u64(originals["v1"], 12, 24)),
            ("v2", originals["v2"][:16]),
            ("v2", replace_u32(originals["v2"], 12, 20)),
            ("v2", replace_u32(originals["v2"], 16, 0)),
            ("v2", replace_u64(originals["v2"], 20, 0)),
            ("v2", replace_u64(originals["v2"], 28, 172)),
            ("v2", replace_u64(originals["v2"], 164, len(originals["v2"]) + 1)),
        ]
        for version, blob in corruptions:
            with self.subTest(version=version, size=len(blob), header=blob[:28]):
                with closing(sqlite3.connect(self.runtime)) as db:
                    db.execute("UPDATE representations SET data=? WHERE name=?", (blob, version))
                    db.commit()
                for full in (False, True):
                    with self.subTest(full=full), self.assertRaises((ValueError, sqlite3.Error)):
                        validate_runtime(self.runtime, full=full)
                with closing(sqlite3.connect(self.runtime)) as db:
                    db.execute("UPDATE representations SET data=? WHERE name=?", (originals[version], version))
                    db.commit()

    def test_body_page_corruption_is_rejected_without_bootstrap_replacement(self):
        # Corrupt a body leaf only: metadata and the binary blobs remain intact.
        # This distinguishes a whole-file SQLite check from a metadata probe.
        with closing(sqlite3.connect(self.runtime)) as db:
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            # The one-row fixture fits in the table's root leaf, so this probe
            # does not require SQLite's optional dbstat virtual table.
            page = db.execute(
                "SELECT rootpage FROM sqlite_master WHERE type='table' AND name='objects'"
            ).fetchone()[0]
        with self.runtime.open("r+b") as stream:
            stream.seek((page - 1) * page_size)
            stream.write(bytes(page_size))
        before = self.runtime.read_bytes()
        with self.assertRaises((ValueError, sqlite3.Error)):
            validate_runtime(self.runtime, full=True)
        with self.assertRaises((ValueError, sqlite3.Error)):
            bootstrap_database(self.runtime, bootstrap=self.bootstrap)
        with patch.dict(os.environ, {"ASTROVERSE_CATALOG_MODE": "offline",
                                     "ASTROVERSE_SECTOR_PATH": str(self.runtime)}):
            with self.assertRaises((ValueError, sqlite3.Error)):
                ensure_runtime(self.root / "absent.json")
        self.assertEqual(self.runtime.read_bytes(), before)

    def test_patched_working_revision_survives_restart_without_bootstrap_or_json(self):
        initial_revision = validate_runtime(self.runtime)["catalog_revision"]
        changed = {"id": "sun", "name": "Updated Sun", "kind": "star", "scale": "solar"}
        publish_changes(self.runtime, expected_revision=initial_revision, upserts=[changed])
        published_revision = validate_runtime(self.runtime)["catalog_revision"]
        self.assertNotEqual(initial_revision, published_revision)
        before = self.runtime.read_bytes()
        self.source.unlink()
        with patch("data.streaming_catalog.validate_record", side_effect=AssertionError("startup normalized bodies")), \
                patch.object(DiskCatalog, "__iter__", side_effect=AssertionError("startup iterated bodies")):
            bootstrap_database(self.runtime, bootstrap=self.root / "unavailable.sqlite")
            with DiskCatalog(self.runtime).snapshot() as snapshot:
                self.assertEqual(snapshot.metadata["catalog_revision"], published_revision)
                self.assertEqual(snapshot.object("sun"), changed)
        self.assertEqual(self.runtime.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
