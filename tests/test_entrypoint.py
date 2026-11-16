"""Docker startup opens SQLite only; preparation remains an explicit command."""

import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

from backend import entrypoint


class EntrypointTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.args = patch.object(sys, "argv", ["entrypoint.py", "uvicorn", "app:app"])
        self.args.start()
        self.addCleanup(self.args.stop)
        self.runtime = patch.object(entrypoint, "ensure_runtime", return_value="runtime/catalog.sqlite").start()
        self.execute = patch.object(entrypoint.os, "execvp").start()
        self.addCleanup(patch.stopall)

    def test_default_offline_open_precedes_api(self):
        self.execute.side_effect = lambda *_: self.runtime.assert_called_once_with(full=False)
        entrypoint.main()
        self.execute.assert_called_once_with("uvicorn", ["uvicorn", "app:app"])

    def test_runtime_failure_prevents_api_without_fallback(self):
        for error in (ValueError("unsupported schema"), OSError("missing publication"), sqlite3.DatabaseError("corrupt")):
            with self.subTest(error=error), self.assertLogs(entrypoint.LOG, level="ERROR"):
                self.runtime.side_effect = error
                self.assertEqual(entrypoint.main(), 1)
            self.execute.assert_not_called()

    def test_one_off_commands_do_not_open_or_prepare_catalog(self):
        with patch.object(sys, "argv", ["entrypoint.py", "python", "-m", "unittest"]):
            entrypoint.main()
        self.runtime.assert_not_called()
        self.execute.assert_called_once_with("python", ["python", "-m", "unittest"])

    def test_missing_command(self):
        with patch.object(sys, "argv", ["entrypoint.py"]), self.assertLogs(entrypoint.LOG, level="ERROR"):
            self.assertEqual(entrypoint.main(), 1)
        self.runtime.assert_not_called()
        self.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
