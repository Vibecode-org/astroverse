"""Build disk artifacts in a separate process, before loading catalog data in API."""

import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from data.coordinates import coordinate_contract
from data.sectors import SectorIndex
from data.streaming_catalog import BUILDER_VERSION, build_streaming_index


def signature(source):
    stat = source.stat()
    return [str(source.resolve()), stat.st_size, stat.st_mtime_ns]


def ensure_runtime(source):
    target = Path(os.environ.get("ASTROVERSE_SECTOR_PATH") or source.with_suffix(".runtime.sqlite"))
    if os.environ.get("ASTROVERSE_CATALOG_MODE") == "published":
        if not os.environ.get("ASTROVERSE_SECTOR_PATH"):
            raise ValueError("published mode requires ASTROVERSE_SECTOR_PATH")
        from data.runtime_catalog import DiskCatalog
        DiskCatalog(target)
        return target
    expected = signature(source)
    try:
        metadata = SectorIndex(target).metadata
        if (metadata.get("source_signature") == expected
                and metadata.get("coordinates") == coordinate_contract()
                and metadata.get("builder") == BUILDER_VERSION):
            return target
    except (OSError, ValueError, sqlite3.Error):
        pass
    subprocess.run([sys.executable, "-m", "backend.prepare_runtime", str(source), str(target)],
                   cwd=Path(__file__).resolve().parents[1], check=True)
    return target


def main():
    source, target = map(Path, sys.argv[1:])
    previous = None
    try:
        SectorIndex(target)
        previous = target
    except (OSError, ValueError, sqlite3.Error):
        pass
    from data.incremental_catalog import publication_lock
    with publication_lock(target):
        build_streaming_index(target, source, source_signature=signature(source), previous_path=previous)


if __name__ == "__main__":
    main()
