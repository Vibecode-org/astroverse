"""Prepare the catalog before the Docker API process starts."""

import logging
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.build_catalog import SourceError, build_enriched_catalog
from data.catalog import load_catalog

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
            if mode in {"offline", "online"}:
                LOG.info("Preparing catalog before API startup: %s", mode)
                build_enriched_catalog(offline=mode == "offline")
            elif mode == "existing":
                load_catalog()
                LOG.info("Using validated existing catalog")
            else:
                raise ValueError("ASTROVERSE_CATALOG_MODE must be offline, online or existing")
        except (SourceError, ValueError, OSError, KeyError, TypeError) as exc:
            LOG.error("Catalog preparation failed; API will not start: %s", exc)
            return 1

    # Replace the entrypoint so Uvicorn receives Docker stop signals directly.
    os.execvp(command[0], command)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
