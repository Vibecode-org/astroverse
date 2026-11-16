"""Explicit JSON preparation and authoritative SQLite startup selection."""

import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.prepare_runtime import ensure_runtime
from data.runtime_catalog import DiskCatalog
from data.sectors import SectorIndex, build_sector_index
from tests.test_sectors import star


class RuntimePreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "input.json"
        self.source.write_text(json.dumps([star("a", 10)]))
        self.target = self.source.with_suffix(".runtime.sqlite")
        env = patch.dict(os.environ, {"ASTROVERSE_CATALOG_MODE": "offline", "ASTROVERSE_SECTOR_PATH": str(self.target)})
        env.start()
        self.addCleanup(env.stop)

    def test_explicit_missing_sqlite_never_builds_json(self):
        with patch("backend.prepare_runtime.subprocess.run", side_effect=AssertionError("runtime preparation")):
            with self.assertRaises(sqlite3.OperationalError):
                ensure_runtime(self.source)
        self.assertFalse(self.target.exists())

    def test_existing_database_reuses_revision_despite_changed_missing_json(self):
        build_sector_index(self.target, [star("a", 10)])
        before, inode = self.target.read_bytes(), self.target.stat().st_ino
        self.source.write_text("invalid JSON")
        self.assertEqual(ensure_runtime(self.source), self.target)
        self.source.unlink()
        self.assertEqual(ensure_runtime(self.source), self.target)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.target.stat().st_ino, inode)

    def test_bad_coordinates_fail_closed_without_rebuild(self):
        build_sector_index(self.target, [star("a", 10)])
        with sqlite3.connect(self.target) as db:
            db.execute("UPDATE metadata SET value='null' WHERE key='coordinates'")
        before = self.target.read_bytes()
        with self.assertRaises(ValueError):
            ensure_runtime(self.source)
        self.assertEqual(self.target.read_bytes(), before)

    def test_online_existing_and_unknown_modes_require_explicit_preparation(self):
        for mode in ("online", "existing", "typo"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"ASTROVERSE_CATALOG_MODE": mode}):
                with self.assertRaisesRegex(ValueError, "prepare JSON explicitly"):
                    ensure_runtime(self.source)

    def test_published_requires_path(self):
        with patch.dict(os.environ, {"ASTROVERSE_CATALOG_MODE": "published", "ASTROVERSE_SECTOR_PATH": ""}):
            with self.assertRaisesRegex(ValueError, "requires ASTROVERSE_SECTOR_PATH"):
                ensure_runtime(self.source)

    def test_explicit_json_cli_and_failed_import_preserve_previous_publication(self):
        with patch.object(sys, "argv", ["prepare_runtime", str(self.source), str(self.target)]):
            with patch.dict("sys.modules"):
                sys.modules.pop("backend.prepare_runtime", None)
                runpy.run_module("backend.prepare_runtime", run_name="__main__")
        self.assertEqual(len(DiskCatalog(self.target)), 1)
        previous = self.target.read_bytes()
        self.source.write_text("invalid JSON")
        with patch.object(sys, "argv", ["prepare_runtime", str(self.source), str(self.target)]):
            with patch.dict("sys.modules"):
                sys.modules.pop("backend.prepare_runtime", None)
                with self.assertRaises(ValueError):
                    runpy.run_module("backend.prepare_runtime", run_name="__main__")
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertEqual(SectorIndex(self.target).metadata["object_count"], 1)


if __name__ == "__main__":
    unittest.main()
