"""CLI exit behavior and additive binary-write failures are part of the contract."""

from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from data import build_catalog as builder
from data.catalog import load_catalog, validate_catalog
from data.sources import SourceError

ROOT = Path(__file__).resolve().parents[1]


class BuilderCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "objects.json"

    def test_cli_offline_script_builds_valid_json_and_both_binary_versions(self):
        with (patch.object(sys, "argv", ["build_catalog", "--offline", "--output", str(self.output)]),
              patch("logging.basicConfig")):
            runpy.run_path(str(ROOT / "data/build_catalog.py"), run_name="__main__")
        self.assertEqual(len(load_catalog(self.output)), 3471)
        self.assertTrue(self.output.with_suffix(".bin").is_file())
        self.assertTrue(self.output.with_suffix(".v2.bin").is_file())

    def test_cli_reports_source_and_configuration_errors_with_exit_one(self):
        for error in [SourceError("upstream offline"), ValueError("invalid config"), OSError("disk full")]:
            stderr = io.StringIO()
            with (patch.object(sys, "argv", ["build_catalog", "--exoplanets-limit", "10"]),
                  patch.object(builder, "build_enriched_catalog", side_effect=error), redirect_stderr(stderr)):
                with self.assertRaises(SystemExit) as raised:
                    builder.main()
                self.assertEqual(raised.exception.code, 1)
                self.assertIn("output was not replaced", stderr.getvalue())

    def test_binary_write_failure_preserves_successful_json_and_logs_warning(self):
        with (patch.object(builder, "write_binary_catalog", side_effect=OSError("disk full")),
              self.assertLogs(builder.LOG, level="WARNING")):
            result = builder.build_enriched_catalog(output=self.output, offline=True)
        self.assertEqual(load_catalog(self.output), result)

    def test_online_wikipedia_path_is_called_only_when_requested(self):
        from tests.test_build_catalog import FakeClient
        with patch.object(builder, "enrich_wikipedia") as enrich:
            builder.build_enriched_catalog(output=self.output, client=FakeClient(), wikipedia=True)
        enrich.assert_called_once()

    def test_extreme_numbers_and_invalid_catalog_shapes_are_rejected(self):
        valid = dict(id="a", name="a", kind="star", scale="local")
        for data in [None, {}, [None], [{**valid, "id": " "}],
                     [{**valid, "kind": "bad"}], [{**valid, "radius_km": 10**1000}],
                     [{**valid, "radius_km": "1"}], [{**valid, "au": -1}]]:
            with self.subTest(data=str(data)[:60]), self.assertRaises(ValueError):
                validate_catalog(data)

    def test_missing_default_catalog_env_and_nonlist_json(self):
        from data.catalog import catalog_path
        with patch.dict(os.environ, {"ASTROVERSE_CATALOG_PATH": "  "}):
            self.assertEqual(catalog_path(), ROOT / "data/objects.json")
        self.output.write_text("{}")
        with self.assertRaises(ValueError):
            load_catalog(self.output)
