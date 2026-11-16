"""Persistent startup, byte-preserving migration and interrupted bootstrap."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from backend.prepare_runtime import ensure_runtime
from data.bootstrap_catalog import bootstrap_database, migrate_database
from data.runtime_catalog import validate_runtime
from data.sectors import build_sector_index
from tests.test_sectors import star


class StartupBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bootstrap = self.root / "bundled.sqlite"
        self.target = self.root / "runtime" / "catalog.sqlite"
        self.metadata = build_sector_index(self.bootstrap, [star("a", 10), star("b", 100)])
        self.write_manifest()
        environment = patch.dict(os.environ, {"ASTROVERSE_CATALOG_MODE": "offline", "ASTROVERSE_SECTOR_PATH": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def write_manifest(self):
        digest = hashlib.sha256(self.bootstrap.read_bytes()).hexdigest()
        Path(str(self.bootstrap) + ".sha256").write_text(digest + "\n")
        Path(str(self.bootstrap) + ".manifest.json").write_text(json.dumps({
            "format": "astroverse-bootstrap/1", "sha256": digest,
            **{key: self.metadata[key] for key in ("catalog_revision", "object_count", "coordinates", "schema_version")},
        }))

    def open(self):
        return bootstrap_database(self.target, bootstrap=self.bootstrap)

    def process(self, code, *args):
        process = subprocess.Popen([sys.executable, "-c", code, *map(str, args)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        return process

    def test_clean_bootstrap_is_exact_copy_and_does_not_read_json(self):
        self.assertEqual(self.open(), self.target)
        self.assertEqual(self.target.read_bytes(), self.bootstrap.read_bytes())
        self.assertEqual(validate_runtime(self.target)["object_count"], 2)
        self.assertFalse((self.root / "objects.json").exists())

    def test_warm_start_preserves_database_after_bootstrap_is_removed(self):
        self.open()
        before, inode = self.target.read_bytes(), self.target.stat().st_ino
        self.bootstrap.unlink()
        Path(str(self.bootstrap) + ".manifest.json").unlink()
        self.assertEqual(self.open(), self.target)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.target.stat().st_ino, inode)

    def test_manifest_and_checksum_fail_closed(self):
        for corruption in ("checksum", "manifest"):
            with self.subTest(corruption=corruption):
                self.write_manifest()
                if corruption == "checksum":
                    with self.bootstrap.open("ab") as stream:
                        stream.write(b"corrupt")
                else:
                    manifest = Path(str(self.bootstrap) + ".manifest.json")
                    data = json.loads(manifest.read_text())
                    data["catalog_revision"] = "0" * 64
                    manifest.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    self.open()
                self.assertFalse(self.target.exists())
                self.assertFalse(list(self.target.parent.glob(".catalog.sqlite.bootstrap-*")))

    def test_corrupt_existing_database_is_preserved_and_never_reseeded(self):
        self.target.parent.mkdir()
        self.target.write_bytes(b"corrupt")
        with self.assertRaises(sqlite3.DatabaseError):
            self.open()
        self.assertEqual(self.target.read_bytes(), b"corrupt")

    def test_default_ensure_ignores_removed_json(self):
        self.open()
        with patch("backend.prepare_runtime.DEFAULT_RUNTIME_PATH", self.target), patch(
                "backend.prepare_runtime.subprocess.run", side_effect=AssertionError("JSON builder")):
            self.assertEqual(ensure_runtime(self.root / "missing.json"), self.target)

    def test_migration_preserves_database_bytes_and_semantic_revision(self):
        result = migrate_database(self.bootstrap, self.target)
        self.assertEqual(result, self.target.resolve())
        self.assertEqual(self.target.read_bytes(), self.bootstrap.read_bytes())
        self.assertEqual(validate_runtime(self.target)["catalog_revision"], self.metadata["catalog_revision"])
        with self.assertRaises(FileExistsError):
            migrate_database(self.bootstrap, self.target)

    def test_migration_refuses_missing_incompatible_or_live_wal_source(self):
        with self.assertRaises(FileNotFoundError):
            migrate_database(self.root / "missing.sqlite", self.target)
        with sqlite3.connect(self.bootstrap) as db:
            db.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
        with self.assertRaises(ValueError):
            migrate_database(self.bootstrap, self.target)
        self.assertFalse(self.target.exists())
        Path(str(self.bootstrap) + "-wal").touch()
        with self.assertRaisesRegex(ValueError, "standalone"):
            migrate_database(self.bootstrap, self.target)

    def test_implicit_initialization_requires_explicit_migration_of_legacy_db(self):
        legacy = self.root / "objects.runtime.sqlite"
        legacy.write_bytes(self.bootstrap.read_bytes())
        with patch("backend.prepare_runtime.DEFAULT_RUNTIME_PATH", self.target), patch(
                "backend.prepare_runtime.DATA_DIR", self.root):
            with self.assertRaisesRegex(ValueError, "preserve its revisions"):
                ensure_runtime()
        self.assertFalse(self.target.exists())
        self.assertEqual(legacy.read_bytes(), self.bootstrap.read_bytes())

    def test_concurrent_initializers_publish_once(self):
        code = 'from data.bootstrap_catalog import bootstrap_database; import sys; bootstrap_database(sys.argv[1], bootstrap=sys.argv[2])'
        children = [self.process(code, self.target, self.bootstrap) for _ in range(3)]
        for child in children:
            out, err = child.communicate(timeout=20)
            self.assertEqual(child.returncode, 0, out + err)
        self.assertEqual(self.target.read_bytes(), self.bootstrap.read_bytes())
        self.assertFalse(list(self.target.parent.glob(".catalog.sqlite.bootstrap-*")))

    def test_killed_copy_never_publishes_partial_file_and_next_start_recovers(self):
        marker = self.root / "waiting"
        code = '''
import sys, time
from pathlib import Path
from data.bootstrap_catalog import bootstrap_database
original = Path.replace
def paused(source, target):
    Path(sys.argv[3]).write_text(str(source))
    while True:
        time.sleep(.1)
Path.replace = paused
bootstrap_database(sys.argv[1], bootstrap=sys.argv[2])
'''
        child = self.process(code, self.target, self.bootstrap, marker)
        deadline = time.monotonic() + 10
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(marker.exists(), child.communicate(timeout=1) if child.poll() is not None else "copy did not reach publication")
        abandoned = Path(marker.read_text()).parent
        child.kill()
        child.communicate(timeout=10)
        self.assertFalse(self.target.exists())
        self.assertTrue(abandoned.exists())
        self.open()
        self.assertFalse(abandoned.exists())
        self.assertEqual(self.target.read_bytes(), self.bootstrap.read_bytes())


if __name__ == "__main__":
    unittest.main()
