"""Open persistent runtime SQLite; JSON preparation is an explicit admin CLI."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from data.sectors import SectorIndex
from data.runtime_catalog import validate_runtime
from data.bootstrap_catalog import DATA_DIR, DEFAULT_RUNTIME_PATH, bootstrap_database
from data.publication import publication_lock


def signature(source):
    stat = source.stat()
    return [str(source.resolve()), stat.st_size, stat.st_mtime_ns]


def ensure_runtime(source=None, *, full=True):
    # The historical source argument is accepted for callers but deliberately
    # never opened or stat'ed. JSON changes cannot overwrite published patches.
    mode = os.environ.get("ASTROVERSE_CATALOG_MODE", "offline")
    selected = os.environ.get("ASTROVERSE_SECTOR_PATH", "").strip()
    if mode not in {"offline", "published"}:
        raise ValueError("API startup supports offline or published mode; prepare JSON explicitly with python -m backend.prepare_runtime SOURCE TARGET")
    if mode == "published" and not selected:
        raise ValueError("published mode requires ASTROVERSE_SECTOR_PATH")
    if selected:
        target = Path(selected)
        # An explicitly selected publication is authoritative. Missing, corrupt
        # or incompatible data must never silently revert to the seed catalog.
        validate_runtime(target, full=full)
        return target
    if not DEFAULT_RUNTIME_PATH.exists():
        legacy = next(DATA_DIR.glob("*.runtime.sqlite"), None)
        if legacy is not None:
            raise ValueError(f"legacy SQLite catalog found at {legacy}; preserve its revisions with python -m data.bootstrap_catalog migrate SOURCE {DEFAULT_RUNTIME_PATH}")
    return bootstrap_database(DEFAULT_RUNTIME_PATH, full=full)


def main():
    from data.streaming_catalog import build_streaming_index
    source, target = map(Path, sys.argv[1:])
    if source.resolve() == target.resolve():
        raise ValueError("source and target must differ")
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = None
    try:
        SectorIndex(target)
        previous = target
    except (OSError, ValueError, sqlite3.Error):
        pass
    with publication_lock(target):
        build_streaming_index(target, source, source_signature=signature(source), previous_path=previous)


if __name__ == "__main__":
    main()
