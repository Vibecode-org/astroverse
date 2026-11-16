"""Prepare the catalog before the Docker API process starts."""

import logging
import os
from pathlib import Path
import sys
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.prepare_runtime import ensure_runtime

LOG = logging.getLogger(__name__)


def main():
    command = sys.argv[1:]
    if not command:
        LOG.error("No container command supplied")
        return 1

    # One-off commands (tests, explicit builds, shells) must not trigger a rebuild.
    if command[0] == "uvicorn":
        mode = os.environ.get("ASTROVERSE_CATALOG_MODE", "offline")
        try:
            # The API import performs the full integrity check once; this
            # entrypoint opens/bootstrap-publishes without a duplicate warm scan.
            target = ensure_runtime(full=False)
            LOG.info("Using persistent SQLite catalog (%s): %s", mode, target)
        except (ValueError, OSError, KeyError, TypeError, OverflowError, sqlite3.Error) as exc:
            LOG.error("Catalog preparation failed; API will not start: %s", exc)
            return 1

    # Replace the entrypoint so Uvicorn receives Docker stop signals directly.
    os.execvp(command[0], command)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
