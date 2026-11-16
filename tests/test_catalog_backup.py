"""Admin publication boundaries: coherent backups and fail-closed restores."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from data.catalog_backup import backup_database, restore_database
from data.incremental_catalog import publish_changes
from data.runtime_catalog import DiskCatalog, validate_runtime
from data.streaming_catalog import build_streaming_index
from tests.test_sectors import star


class CatalogBackupTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "working.sqlite"
        self.bundle = self.root / "backup"
        self.target = self.root / "restored.sqlite"
        self.items = [star("a", 10), star("b", 100)]
        self.metadata = build_streaming_index(self.source, None, objects=iter(self.items),
                                             manifest={"source": "test", "version": 1})

    def backup(self):
        return backup_database(self.source, self.bundle)

    def edit_manifest(self, mutate):
        path = self.bundle / "manifest.json"
        value = json.loads(path.read_text())
        mutate(value)
        path.write_text(json.dumps(value))

    def process(self, code, *args):
        child = subprocess.Popen([sys.executable, "-c", code, *map(str, args)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.stop_process, child)
        return child

    @staticmethod
    def stop_process(child):
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)

    def wait_file(self, marker, child):
        deadline = time.monotonic() + 20
        while not marker.exists():
            if child.poll() is not None:
                self.fail(str(child.communicate()))
            if time.monotonic() > deadline:
                self.fail("process failed to reach controlled publication boundary")
            time.sleep(.01)

    def test_roundtrip_is_byte_exact_including_patch_history_and_manifests(self):
        published = publish_changes(self.source, expected_revision=self.metadata["catalog_revision"],
                                    upserts=[dict(self.items[0], description="admin correction")])
        before = self.source.read_bytes()
        with patch.object(DiskCatalog, "__iter__", side_effect=AssertionError("materialized catalog")), \
                patch("data.streaming_catalog.validate_record", side_effect=AssertionError("normalized body")):
            self.backup()
            restore_database(self.bundle, self.target)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(validate_runtime(self.target), published)
        self.assertIn("previous_import_manifest", published)

    def test_replace_is_required_and_old_snapshot_reads_old_inode(self):
        self.backup()
        self.target.write_bytes(self.source.read_bytes())
        published = publish_changes(self.target, expected_revision=self.metadata["catalog_revision"],
                                    upserts=[dict(self.items[0], description="new active state")])
        before = self.target.read_bytes()
        with self.assertRaises(FileExistsError):
            restore_database(self.bundle, self.target)
        self.assertEqual(self.target.read_bytes(), before)
        with DiskCatalog(self.target).snapshot() as pinned:
            inode = self.target.stat().st_ino
            restore_database(self.bundle, self.target, replace=True)
            self.assertNotEqual(inode, self.target.stat().st_ino)
            self.assertEqual(pinned.metadata["catalog_revision"], published["catalog_revision"])
            self.assertEqual(pinned.object("a")["description"], "new active state")
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_backup_never_overwrites_existing_bundle(self):
        self.backup()
        with self.assertRaises(FileExistsError):
            self.backup()

    def test_wrong_checksum_and_corrupt_database_preserve_target(self):
        self.backup()
        self.target.write_bytes(self.source.read_bytes())
        before = self.target.read_bytes()
        self.edit_manifest(lambda value: value.update(sha256="0" * 64))
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            restore_database(self.bundle, self.target, replace=True)
        self.assertEqual(self.target.read_bytes(), before)
        # A matching checksum does not make corrupted bytes a valid database.
        database = self.bundle / "catalog.sqlite"
        database.write_bytes(b"not SQLite")
        self.edit_manifest(lambda value: value.update(sha256=hashlib.sha256(database.read_bytes()).hexdigest()))
        with self.assertRaises((ValueError, sqlite3.Error)):
            restore_database(self.bundle, self.target, replace=True)
        self.assertEqual(self.target.read_bytes(), before)

    def test_future_schema_and_capabilities_are_refused_before_publication(self):
        self.backup()
        original = (self.bundle / "manifest.json").read_bytes()
        for key, value in (("schema_version", 999), ("incremental_schema", 999), ("builder", "future/99")):
            with self.subTest(key=key):
                (self.bundle / "manifest.json").write_bytes(original)
                self.edit_manifest(lambda item: item["compatibility"].update({key: value}))
                with self.assertRaisesRegex(ValueError, "incompatible"):
                    restore_database(self.bundle, self.target)
                self.assertFalse(self.target.exists())

    def test_corrupt_body_page_with_matching_checksum_still_fails_integrity(self):
        self.backup()
        database = self.bundle / "catalog.sqlite"
        with sqlite3.connect(database) as db:
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            page = db.execute("SELECT rootpage FROM sqlite_master WHERE name='objects'").fetchone()[0]
        with database.open("r+b") as stream:
            stream.seek((page - 1) * page_size)
            stream.write(bytes(page_size))
        self.edit_manifest(lambda item: item.update(sha256=hashlib.sha256(database.read_bytes()).hexdigest()))
        self.target.write_bytes(self.source.read_bytes())
        before = self.target.read_bytes()
        with self.assertRaises((ValueError, sqlite3.Error)):
            restore_database(self.bundle, self.target, replace=True)
        self.assertEqual(self.target.read_bytes(), before)

    def test_backup_validates_source_before_publishing_bundle(self):
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
        with self.assertRaises(ValueError):
            self.backup()
        self.assertFalse(self.bundle.exists())
        self.assertFalse(list(self.root.glob(".backup.backup-*")))

    def test_oversized_metadata_cannot_publish_an_unrestorable_backup(self):
        with sqlite3.connect(self.source) as db:
            db.execute("INSERT INTO metadata VALUES ('admin_note',?)", (json.dumps("x" * (1024 * 1024)),))
        with self.assertRaisesRegex(ValueError, "manifest exceeds"):
            self.backup()
        self.assertFalse(self.bundle.exists())
        self.assertFalse(list(self.root.glob(".backup.backup-*")))

    def test_matching_checksum_cannot_hide_incompatible_sqlite(self):
        self.backup()
        database = self.bundle / "catalog.sqlite"
        with sqlite3.connect(database) as db:
            db.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
        self.edit_manifest(lambda item: item.update(sha256=hashlib.sha256(database.read_bytes()).hexdigest()))
        with self.assertRaisesRegex(ValueError, "schema"):
            restore_database(self.bundle, self.target)
        self.assertFalse(self.target.exists())

    def test_manifest_metadata_must_match_actual_database(self):
        self.backup()
        self.edit_manifest(lambda item: item["metadata"].update(parent_revision="0" * 64))
        with self.assertRaisesRegex(ValueError, "metadata does not match"):
            restore_database(self.bundle, self.target)
        self.assertFalse(self.target.exists())

    def test_wal_and_journal_sources_targets_are_refused(self):
        for suffix in ("-wal", "-journal"):
            sidecar = Path(str(self.source) + suffix)
            sidecar.touch()
            with self.assertRaisesRegex(ValueError, "standalone"):
                self.backup()
            sidecar.unlink()
        self.backup()
        sidecar = Path(str(self.target) + "-wal")
        sidecar.touch()
        with self.assertRaisesRegex(ValueError, "WAL/journal"):
            restore_database(self.bundle, self.target)
        self.assertFalse(self.target.exists())

    def test_injected_copy_fsync_and_rename_failures_leave_existing_target(self):
        self.backup()
        self.target.write_bytes(self.source.read_bytes())
        before, inode = self.target.read_bytes(), self.target.stat().st_ino
        original_replace = Path.replace

        def fail_replace(source, target):
            if Path(target) == self.target:
                raise OSError("injected pre-rename failure")
            return original_replace(source, target)

        for injection in (patch("data.catalog_backup._copy", side_effect=OSError("copy failure")),
                          patch("os.fsync", side_effect=OSError("fsync failure")),
                          patch.object(Path, "replace", fail_replace)):
            with injection, self.assertRaises(OSError):
                restore_database(self.bundle, self.target, replace=True)
            self.assertEqual(self.target.read_bytes(), before)
            self.assertEqual(self.target.stat().st_ino, inode)
            self.assertFalse(list(self.root.glob(".restored.sqlite.restore-*")))

    def test_metrics_measure_file_work_without_materializing_rows(self):
        backup, restore = {}, {}
        backup_database(self.source, self.bundle, backup)
        restore_database(self.bundle, self.target, metrics=restore)
        for metrics in (backup, restore):
            self.assertEqual(metrics["file_bytes"], self.source.stat().st_size)
            for field in ("copy_seconds", "hash_seconds", "validation_seconds", "publication_seconds", "total_seconds"):
                self.assertGreaterEqual(metrics[field], 0)

    def test_backup_holds_same_lock_as_patch_writer_and_pins_one_revision(self):
        ready, gate, writer_started = (self.root / name for name in ("ready", "gate", "writer"))
        backup = self.process('''
import sys,time
from pathlib import Path
import data.catalog_backup as module
source,bundle,ready,gate=sys.argv[1:]
original=module._copy
def pause(*args):
    Path(ready).touch()
    while not Path(gate).exists(): time.sleep(.01)
    return original(*args)
module._copy=pause
module.backup_database(source,bundle)
''', self.source, self.bundle, ready, gate)
        self.wait_file(ready, backup)
        writer = self.process('''
import sys
from pathlib import Path
from data.incremental_catalog import publish_changes
source,revision,marker=sys.argv[1:]
Path(marker).touch()
publish_changes(source,expected_revision=revision,upserts=[dict(id='new',name='new',kind='star',scale='local')])
''', self.source, self.metadata["catalog_revision"], writer_started)
        self.wait_file(writer_started, writer)
        time.sleep(.1)
        self.assertIsNone(writer.poll(), "patch writer did not wait for publication lock")
        gate.touch()
        for child in (backup, writer):
            output, errors = child.communicate(timeout=30)
            self.assertEqual(child.returncode, 0, output + errors)
        restore_database(self.bundle, self.target)
        self.assertEqual(validate_runtime(self.target)["catalog_revision"], self.metadata["catalog_revision"])
        self.assertNotEqual(validate_runtime(self.source)["catalog_revision"], self.metadata["catalog_revision"])

    def test_killed_backup_and_restore_never_publish_partial_files(self):
        self.target.write_bytes(self.source.read_bytes())
        before = self.target.read_bytes()
        for action in ("backup", "restore"):
            with self.subTest(action=action):
                marker = self.root / (action + ".ready")
                child = self.process('''
import sys,time
from pathlib import Path
from data.catalog_backup import backup_database,restore_database
action,source,bundle,target,marker=sys.argv[1:]
original=Path.replace
def pause(stage,destination):
    if Path(destination)==Path(bundle if action=='backup' else target):
        Path(marker).write_text(str(stage.parent if action=='restore' else stage))
        while True: time.sleep(.1)
    return original(stage,destination)
Path.replace=pause
if action=='backup': backup_database(source,bundle)
else: restore_database(bundle,target,replace=True)
''', action, self.source, self.bundle, self.target, marker)
                self.wait_file(marker, child)
                abandoned = Path(marker.read_text())
                child.kill()
                child.communicate(timeout=10)
                self.assertTrue(abandoned.exists())
                self.assertEqual(self.target.read_bytes(), before)
                if action == "backup":
                    self.assertFalse(self.bundle.exists())
                    self.backup()
                else:
                    restore_database(self.bundle, self.target, replace=True)
                self.assertFalse(abandoned.exists())


if __name__ == "__main__":
    unittest.main()
