"""Explicit catalog preparation and verified, atomic SQLite bootstrap.

The bundled artifact is prepared explicitly before image build. Ordinary API startup
never opens its JSON input or normalizes records. Only the first startup copies
the bundled SQLite file; subsequent starts open the persistent publication.
"""

import argparse
from contextlib import ExitStack
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from data.runtime_catalog import validate_runtime
from data.publication import publication_lock as _lock, fsync_directory as _fsync_directory

DATA_DIR = Path(__file__).resolve().parent
DEFAULT_RUNTIME_PATH = DATA_DIR / "runtime" / "catalog.sqlite"
DEFAULT_BOOTSTRAP_PATH = DATA_DIR / "bootstrap" / "catalog.sqlite"
DEFAULT_RELEASE_PATH = DATA_DIR / "bootstrap" / "release.json"
LOG = logging.getLogger(__name__)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _publish_copy(source, target, *, expected_sha256=None, manifest=None):
    """Copy one pinned source inode; never publish an incomplete file."""
    prefix = f".{target.name}.bootstrap-"
    # Only a process holding this target's permanent lock removes abandoned
    # bootstrap directories. Other publications and unrelated files are intact.
    for old in target.parent.iterdir():
        if old.name.startswith(prefix) and old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=prefix) as directory:
        temporary = Path(directory) / "catalog.sqlite"
        digest = hashlib.sha256()
        started = time.perf_counter()
        with source.open("rb") as incoming, temporary.open("wb") as outgoing:
            while chunk := incoming.read(1024 * 1024):
                digest.update(chunk)
                outgoing.write(chunk)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        LOG.info("SQLite copy/checksum: %.6fs, %s bytes (O(N) file work)",
                 time.perf_counter() - started, temporary.stat().st_size)
        if expected_sha256 is not None and digest.hexdigest() != expected_sha256:
            raise ValueError("bootstrap SQLite checksum mismatch")
        metadata = validate_runtime(temporary, full=True)
        # Runtime publications use immutable DELETE-journal files, never a live
        # WAL database whose latest transactions could be outside the copied file.
        with sqlite3.connect(temporary) as db:
            if db.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("migration requires a standalone DELETE-journal SQLite publication")
        if manifest is not None:
            for key in ("catalog_revision", "object_count", "coordinates", "schema_version"):
                if metadata.get(key) != manifest.get(key):
                    raise ValueError(f"bootstrap manifest mismatch: {key}")
        temporary.replace(target)
        _fsync_directory(target.parent)
    return metadata


def build_bootstrap(source, target):
    """Build the shipped fixture explicitly, with reproducible provenance."""
    from data.streaming_catalog import build_streaming_index
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with _lock(target):
        metadata = build_streaming_index(target, source)
        validate_runtime(target, full=True)
        digest = sha256_file(target)
        manifest = {
            "format": "astroverse-bootstrap/1", "sha256": digest,
            "source": source.name, "source_sha256": sha256_file(source),
            **{key: metadata[key] for key in
               ("catalog_revision", "object_count", "coordinates", "schema_version", "builder")},
            "incremental_schema": metadata.get("incremental_schema"),
            "capabilities": {"incremental_schema": metadata.get("incremental_schema")},
            "sqlite_version": sqlite3.sqlite_version,
        }
        Path(str(target) + ".manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        Path(str(target) + ".sha256").write_text(digest + "\n", encoding="ascii")
    return metadata


def _release(path=DEFAULT_RELEASE_PATH):
    release = json.loads(Path(path).read_text(encoding="utf-8"))
    if (not isinstance(release, dict) or release.get("format") != "astroverse-release/1"
            or not isinstance(release.get("artifact_version"), str) or not release["artifact_version"]
            or not isinstance(release.get("expected_metadata"), dict)
            or not {"builder", "catalog_revision", "coordinates", "incremental_schema", "object_count", "schema_version"}
                <= release["expected_metadata"].keys()):
        raise ValueError("invalid pinned bootstrap release")
    for key in ("source_sha256", "artifact_sha256"):
        value = release.get(key)
        if (not isinstance(value, str) or len(value) != 64
                or any(c not in "0123456789abcdef" for c in value)):
            raise ValueError(f"invalid pinned bootstrap release {key}")
    return release


def verify_bootstrap(artifact=DEFAULT_BOOTSTRAP_PATH, *, release=DEFAULT_RELEASE_PATH):
    """Verify delivered bytes and content against the committed release contract.

    The checksum sidecar alone is not trust: release.json independently pins
    fixture identity, semantic content, schema/capabilities and artifact bytes.
    Updating a release is an explicit source-controlled maintenance operation.
    """
    artifact = Path(artifact)
    expected = _release(release)
    manifest = json.loads(Path(str(artifact) + ".manifest.json").read_text(encoding="utf-8"))
    checksum = Path(str(artifact) + ".sha256").read_text(encoding="ascii").strip()
    if (not isinstance(manifest, dict) or manifest.get("format") != "astroverse-bootstrap/1"
            or checksum != expected["artifact_sha256"] or manifest.get("sha256") != checksum
            or sha256_file(artifact) != checksum):
        raise ValueError("delivered bootstrap checksum does not match pinned release")
    for key in ("source", "source_sha256", "sqlite_version"):
        if manifest.get(key) != expected.get(key):
            raise ValueError(f"delivered bootstrap provenance mismatch: {key}")
    metadata = validate_runtime(artifact, full=True)
    for key, value in expected["expected_metadata"].items():
        if metadata.get(key) != value or manifest.get(key) != value:
            raise ValueError(f"delivered bootstrap content mismatch: {key}")
    if manifest.get("capabilities") != {"incremental_schema": metadata.get("incremental_schema")}:
        raise ValueError("delivered bootstrap capabilities mismatch")
    return metadata


def prepare_bootstrap(source, target, *, release=DEFAULT_RELEASE_PATH):
    """Reproduce the pinned release; never bless arbitrary fixture input."""
    source, target = Path(source), Path(target)
    expected = _release(release)
    if source.name != expected["source"] or sha256_file(source) != expected["source_sha256"]:
        raise ValueError("input fixture does not match pinned bootstrap release")
    # Prepare privately first, so failed reproducibility cannot replace an
    # existing artifact. The three files are release assets, not runtime state.
    target.parent.mkdir(parents=True, exist_ok=True)
    with _lock(target), tempfile.TemporaryDirectory(dir=target.parent, prefix=".release-") as temporary:
        candidate = Path(temporary) / target.name
        build_bootstrap(source, candidate)
        metadata = verify_bootstrap(candidate, release=release)
        for suffix in (".manifest.json", ".sha256", ""):
            Path(str(candidate) + suffix).replace(Path(str(target) + suffix))
        _fsync_directory(target.parent)
    return metadata


def bootstrap_database(target=DEFAULT_RUNTIME_PATH, *, bootstrap=DEFAULT_BOOTSTRAP_PATH, full=True):
    """Open existing publication, or verify/copy the bundled initial database."""
    target, bootstrap = Path(target), Path(bootstrap)
    if target.exists() or target.is_symlink():
        validate_runtime(target, full=full)
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with _lock(target):
        if target.exists() or target.is_symlink():
            validate_runtime(target, full=full)
            return target
        if bootstrap.resolve() == DEFAULT_BOOTSTRAP_PATH.resolve():
            verify_bootstrap(bootstrap)
        expected = Path(str(bootstrap) + ".sha256").read_text(encoding="ascii").strip()
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise ValueError("invalid bootstrap SQLite checksum")
        manifest = json.loads(Path(str(bootstrap) + ".manifest.json").read_text(encoding="utf-8"))
        if (not isinstance(manifest, dict) or manifest.get("format") != "astroverse-bootstrap/1"
                or manifest.get("sha256") != expected):
            raise ValueError("invalid bootstrap provenance manifest")
        _publish_copy(bootstrap, target, expected_sha256=expected, manifest=manifest)
    return target


def migrate_database(source, target):
    """Explicitly copy an existing compatible publication, preserving its bytes.

    This moves storage, not scientific models or schema versions. Incompatible
    databases require explicit preparation; no startup rebuild guesses a source.
    """
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target:
        validate_runtime(source, full=True)
        return target
    if not source.is_file():
        raise FileNotFoundError(source)
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-journal")):
        raise ValueError("migration requires a closed standalone SQLite publication")
    target.parent.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for path in sorted({source, target}):
            locks.enter_context(_lock(path))
        if target.exists() or target.is_symlink():
            raise FileExistsError(f"migration target already exists: {target}")
        _publish_copy(source, target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "prepare", "verify", "migrate"))
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action != "verify" and args.target is None:
        parser.error("target is required for build/prepare/migrate")
    if args.action == "build":
        build_bootstrap(args.source, args.target)
    elif args.action == "prepare":
        prepare_bootstrap(args.source, args.target)
    elif args.action == "verify":
        verify_bootstrap(args.source)
    else:
        migrate_database(args.source, args.target)


if __name__ == "__main__":
    main()
