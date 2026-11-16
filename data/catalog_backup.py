"""Verified, byte-preserving admin backup/restore for immutable publications.

Bundles are directories published by one atomic rename. Cooperative writers
share publication_lock; live WAL/journal databases are deliberately rejected.
No body payloads are deserialized, regenerated, or normalized.
"""

import argparse
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from data.publication import publication_lock, fsync_directory
from data.runtime_catalog import validate_runtime
from data.sectors import SCHEMA_VERSION
from data.incremental_index import INCREMENTAL_SCHEMA

FORMAT = "astroverse-backup/1"
CHUNK_BYTES = 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


def _standalone(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-journal")):
        raise ValueError("backup/restore requires a standalone DELETE-journal publication")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
            raise ValueError("backup/restore requires a standalone DELETE-journal publication")


def _compatibility(metadata):
    return {key: metadata.get(key) for key in ("schema_version", "builder", "incremental_schema")}


def _check_compatibility(value):
    # Schema2's pre-incremental artifact is readable too. Reject unknown future
    # capabilities rather than silently downgrading a database on restore.
    if (not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION
            or value.get("incremental_schema") not in (None, INCREMENTAL_SCHEMA)
            or value.get("builder") not in (None, "streaming/1")):
        raise ValueError("incompatible backup schema/capabilities")


def _copy(source, destination, metrics):
    digest = hashlib.sha256()
    copied = 0
    hashing = 0.0
    started = time.perf_counter()
    # One open inode is pinned throughout; the source publication lock prevents
    # cooperative replacement until the copy/validation has finished.
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        while chunk := incoming.read(CHUNK_BYTES):
            then = time.perf_counter()
            digest.update(chunk)
            hashing += time.perf_counter() - then
            copied += len(chunk)
            outgoing.write(chunk)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    metrics.update(copy_seconds=time.perf_counter() - started - hashing,
                   hash_seconds=hashing, file_bytes=copied)
    return digest.hexdigest()


def _staging(target, kind):
    prefix = f".{target.name}.{kind}-"
    # Called only while the permanent publication lock is held.
    for abandoned in target.parent.iterdir():
        if abandoned.name.startswith(prefix) and abandoned.is_dir() and not abandoned.is_symlink():
            shutil.rmtree(abandoned)
    return tempfile.TemporaryDirectory(dir=target.parent, prefix=prefix)


def _write_manifest(path, manifest):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("backup manifest exceeds 1 MiB")


def backup_database(source, bundle, metrics=None):
    """Publish a new immutable backup bundle; existing bundles are never replaced."""
    started = time.perf_counter()
    metrics = metrics if metrics is not None else {}
    source, bundle = Path(source).resolve(), Path(bundle).resolve()
    if source == bundle or bundle in source.parents:
        raise ValueError("source publication and backup bundle must differ")
    bundle.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        # Stable order also prevents two reversed admin operations deadlocking.
        for path in sorted({source, bundle}):
            locks.enter_context(publication_lock(path))
        if bundle.exists() or bundle.is_symlink():
            raise FileExistsError(f"backup bundle already exists: {bundle}")
        _standalone(source)
        with _staging(bundle, "backup") as directory:
            stage = Path(directory)
            database = stage / "catalog.sqlite"
            digest = _copy(source, database, metrics)
            then = time.perf_counter()
            metadata = validate_runtime(database, full=True)
            compatibility = _compatibility(metadata)
            _check_compatibility(compatibility)
            metrics["validation_seconds"] = time.perf_counter() - then
            _write_manifest(stage / "manifest.json", {
                "format": FORMAT, "sha256": digest, "metadata": metadata,
                "compatibility": compatibility,
                "provenance": {"source_catalog_revision": metadata["catalog_revision"]},
            })
            fsync_directory(stage)
            then = time.perf_counter()
            stage.replace(bundle)
            fsync_directory(bundle.parent)
            metrics["publication_seconds"] = time.perf_counter() - then
    metrics["total_seconds"] = time.perf_counter() - started
    return bundle


def _manifest(bundle):
    path = bundle / "manifest.json"
    # Metadata manifests have no object payloads; reject unexpectedly huge input.
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("backup manifest exceeds 1 MiB")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ValueError("unsupported backup manifest format")
    digest = manifest.get("sha256")
    if (not isinstance(digest, str) or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("invalid backup checksum")
    _check_compatibility(manifest.get("compatibility"))
    metadata = manifest.get("metadata")
    if (not isinstance(metadata, dict) or _compatibility(metadata) != manifest["compatibility"]
            or manifest.get("provenance") != {"source_catalog_revision": metadata.get("catalog_revision")}):
        raise ValueError("inconsistent backup metadata/provenance")
    return manifest


def restore_database(bundle, target, *, replace=False, metrics=None):
    """Verify a bundle, then atomically publish it; --replace is explicit."""
    started = time.perf_counter()
    metrics = metrics if metrics is not None else {}
    bundle, target = Path(bundle).resolve(), Path(target).resolve()
    if target == bundle or bundle in target.parents:
        raise ValueError("restore target must be outside the backup bundle")
    target.parent.mkdir(parents=True, exist_ok=True)
    with publication_lock(target):
        if (target.exists() or target.is_symlink()) and not replace:
            raise FileExistsError(f"restore target exists; use --replace: {target}")
        # Restoring over live SQLite sidecars could replay unrelated transactions.
        if any(Path(str(target) + suffix).exists() for suffix in ("-wal", "-journal")):
            raise ValueError("restore target has live SQLite WAL/journal files")
        manifest = _manifest(bundle)
        source = bundle / "catalog.sqlite"
        _standalone(source)
        with _staging(target, "restore") as directory:
            database = Path(directory) / "catalog.sqlite"
            digest = _copy(source, database, metrics)
            if digest != manifest["sha256"]:
                raise ValueError("backup SQLite checksum mismatch")
            then = time.perf_counter()
            metadata = validate_runtime(database, full=True)
            if metadata != manifest["metadata"]:
                raise ValueError("backup metadata does not match SQLite publication")
            _check_compatibility(_compatibility(metadata))
            metrics["validation_seconds"] = time.perf_counter() - then
            then = time.perf_counter()
            database.replace(target)
            fsync_directory(target.parent)
            metrics["publication_seconds"] = time.perf_counter() - then
    metrics["total_seconds"] = time.perf_counter() - started
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("source", type=Path)
    backup.add_argument("bundle", type=Path)
    restore = commands.add_parser("restore")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("target", type=Path)
    restore.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if args.action == "backup":
        backup_database(args.source, args.bundle)
    else:
        restore_database(args.bundle, args.target, replace=args.replace)


if __name__ == "__main__":
    main()
