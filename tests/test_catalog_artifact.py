"""The shipped database is release-pinned and verifiable without its fixture."""

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from data.bootstrap_catalog import (DEFAULT_BOOTSTRAP_PATH, DEFAULT_RELEASE_PATH,
                                    prepare_bootstrap, sha256_file, verify_bootstrap)
from data.runtime_catalog import DiskCatalog


class CatalogArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.release = json.loads(DEFAULT_RELEASE_PATH.read_text())

    def copy_artifact(self):
        target = self.root / "catalog.sqlite"
        for suffix in ("", ".sha256", ".manifest.json"):
            shutil.copyfile(Path(str(DEFAULT_BOOTSTRAP_PATH) + suffix), Path(str(target) + suffix))
        return target

    def test_delivered_artifact_is_verified_without_json_or_body_normalization(self):
        with patch("data.streaming_catalog.iter_catalog", side_effect=AssertionError("read fixture")), \
                patch.object(DiskCatalog, "__iter__", side_effect=AssertionError("loaded all bodies")):
            metadata = verify_bootstrap()
        self.assertEqual(metadata["object_count"], 3471)
        self.assertEqual(metadata["catalog_revision"], self.release["expected_metadata"]["catalog_revision"])
        self.assertEqual(metadata["incremental_schema"], 1)
        self.assertEqual(sha256_file(DEFAULT_BOOTSTRAP_PATH), self.release["artifact_sha256"])

    def test_prepare_refuses_arbitrary_input_without_changing_existing_output(self):
        source = self.root / self.release["source"]
        source.write_text("[]")
        target = self.root / "catalog.sqlite"
        target.write_bytes(b"existing release")
        with self.assertRaisesRegex(ValueError, "fixture does not match"):
            prepare_bootstrap(source, target)
        self.assertEqual(target.read_bytes(), b"existing release")

    def test_rechecksum_and_manifest_cannot_bless_an_arbitrary_artifact(self):
        artifact = self.copy_artifact()
        # SQLite remains structurally valid; this is different catalog content.
        with sqlite3.connect(artifact) as db:
            db.execute("UPDATE objects SET payload=replace(payload,'Солнце','Altered Sun') WHERE id='sun'")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        Path(str(artifact) + ".sha256").write_text(digest + "\n")
        path = Path(str(artifact) + ".manifest.json")
        manifest = json.loads(path.read_text())
        manifest["sha256"] = digest
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "pinned release"):
            verify_bootstrap(artifact)

    def test_provenance_and_capabilities_are_independently_pinned(self):
        artifact = self.copy_artifact()
        path = Path(str(artifact) + ".manifest.json")
        original = path.read_text()
        for key, value in (("source_sha256", "0" * 64), ("source", "other.json"),
                           ("catalog_revision", "0" * 64), ("incremental_schema", 999),
                           ("capabilities", {})):
            with self.subTest(key=key):
                manifest = json.loads(original)
                manifest[key] = value
                path.write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):
                    verify_bootstrap(artifact)

    def test_two_preparations_reproduce_exact_delivered_database_and_manifest(self):
        # The preparation environment is part of the release contract. Ordinary
        # runtime verification works on any supported Python/SQLite reader.
        if sqlite3.sqlite_version != self.release["sqlite_version"]:
            self.skipTest("reproducible preparation requires release SQLite " + self.release["sqlite_version"])
        source = DEFAULT_BOOTSTRAP_PATH.parent.parent / self.release["source"]
        first = self.root / "first" / "catalog.sqlite"
        second = self.root / "second" / "catalog.sqlite"
        prepare_bootstrap(source, first)
        prepare_bootstrap(source, second)
        for suffix in ("", ".sha256", ".manifest.json"):
            expected = Path(str(DEFAULT_BOOTSTRAP_PATH) + suffix).read_bytes()
            self.assertEqual(Path(str(first) + suffix).read_bytes(), expected)
            self.assertEqual(Path(str(second) + suffix).read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
