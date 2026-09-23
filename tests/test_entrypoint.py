"""Docker startup sequencing without live network calls or process replacement."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import entrypoint


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        args = patch.object(sys, "argv", ["entrypoint.py", "uvicorn", "app:app"])
        args.start()
        self.addCleanup(args.stop)
        self.build = patch.object(entrypoint, "build_enriched_catalog").start()
        self.load = patch.object(entrypoint, "load_catalog").start()
        self.exec = patch.object(entrypoint.os, "execvp").start()
        self.addCleanup(patch.stopall)

    def test_default_offline_build_precedes_api(self):
        self.exec.side_effect = lambda *_: self.build.assert_called_once_with(offline=True)
        entrypoint.main()
        self.exec.assert_called_once_with("uvicorn", ["uvicorn", "app:app"])
        self.load.assert_not_called()

    def test_online_mode(self):
        os.environ["ASTROVERSE_CATALOG_MODE"] = "online"
        entrypoint.main()
        self.build.assert_called_once_with(offline=False)
        self.exec.assert_called_once()

    def test_existing_mode_validates_without_rebuild(self):
        os.environ["ASTROVERSE_CATALOG_MODE"] = "existing"
        self.exec.side_effect = lambda *_: self.load.assert_called_once_with()
        entrypoint.main()
        self.build.assert_not_called()
        self.exec.assert_called_once()

    def test_failed_build_prevents_api_start(self):
        for error in (entrypoint.SourceError("HTTP 403"), ValueError("duplicate ID"), OSError("read-only")):
            with self.subTest(error=error), self.assertLogs(entrypoint.LOG, level="ERROR"):
                self.build.side_effect = error
                self.assertEqual(entrypoint.main(), 1)
            self.exec.assert_not_called()

    def test_invalid_existing_catalog_prevents_api_start(self):
        os.environ["ASTROVERSE_CATALOG_MODE"] = "existing"
        self.load.side_effect = FileNotFoundError("No catalog")
        with self.assertLogs(entrypoint.LOG, level="ERROR"):
            self.assertEqual(entrypoint.main(), 1)
        self.exec.assert_not_called()

    def test_invalid_mode_prevents_api_start(self):
        os.environ["ASTROVERSE_CATALOG_MODE"] = "typo"
        with self.assertLogs(entrypoint.LOG, level="ERROR"):
            self.assertEqual(entrypoint.main(), 1)
        self.exec.assert_not_called()
        self.build.assert_not_called()

    def test_one_off_commands_do_not_build_or_validate(self):
        with patch.object(sys, "argv", ["entrypoint.py", "python", "-m", "unittest"]):
            entrypoint.main()
        self.build.assert_not_called()
        self.load.assert_not_called()
        self.exec.assert_called_once_with("python", ["python", "-m", "unittest"])

    def test_missing_command(self):
        with patch.object(sys, "argv", ["entrypoint.py"]), self.assertLogs(entrypoint.LOG, level="ERROR"):
            self.assertEqual(entrypoint.main(), 1)
        self.exec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
