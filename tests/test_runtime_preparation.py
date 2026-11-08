"""Startup artifact freshness and failure isolation, without a live server."""

import json
import os
from pathlib import Path
import runpy
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.prepare_runtime import ensure_runtime
from data.runtime_catalog import DiskCatalog
from data.sectors import SectorIndex
from tests.test_sectors import star


class RuntimePreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.source = Path(self.tmp.name) / "input.json"
        self.source.write_text(json.dumps([star("a", 10)]))
        env = patch.dict(os.environ, {"ASTROVERSE_SECTOR_PATH": ""})
        env.start()
        self.addCleanup(env.stop)

    def test_missing_artifact_is_built_outside_worker_and_fresh_is_reused(self):
        target = ensure_runtime(self.source)
        self.assertEqual(target, self.source.with_suffix(".runtime.sqlite"))
        self.assertEqual(len(DiskCatalog(target)), 1)
        with patch("backend.prepare_runtime.subprocess.run", side_effect=AssertionError("rebuild")):
            self.assertEqual(ensure_runtime(self.source), target)

    def test_source_and_contract_changes_invalidate_artifact(self):
        target = ensure_runtime(self.source)
        before = SectorIndex(target).metadata["catalog_revision"]
        self.source.write_text(json.dumps([star("b", 100)]))
        ensure_runtime(self.source)
        self.assertNotEqual(SectorIndex(target).metadata["catalog_revision"], before)
        # Same source stat with an obsolete coordinates contract still rebuilds.
        with sqlite3.connect(target) as db:
            db.execute("UPDATE metadata SET value='null' WHERE key='coordinates'")
        ensure_runtime(self.source)
        self.assertIsInstance(SectorIndex(target).metadata["coordinates"], dict)

    def test_failed_rebuild_never_accepts_stale_artifact(self):
        target = ensure_runtime(self.source)
        previous = target.read_bytes()
        self.source.write_text("invalid JSON")
        with patch("backend.prepare_runtime.subprocess.run", side_effect=subprocess.CalledProcessError(1, "builder")):
            with self.assertRaises(subprocess.CalledProcessError):
                ensure_runtime(self.source)
        self.assertEqual(target.read_bytes(), previous)
        self.source.unlink()
        with self.assertRaises(FileNotFoundError):
            ensure_runtime(self.source)

    def test_explicit_path_and_cli(self):
        destination = Path(self.tmp.name) / "custom.sqlite"
        with patch.object(sys, "argv", ["prepare_runtime", str(self.source), str(destination)]):
            with patch.dict("sys.modules"):
                sys.modules.pop("backend.prepare_runtime", None)
                runpy.run_module("backend.prepare_runtime", run_name="__main__")
        with patch.dict(os.environ, {"ASTROVERSE_SECTOR_PATH": str(destination)}):
            self.assertEqual(ensure_runtime(self.source), destination)
