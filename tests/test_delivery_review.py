"""Independent interoperation probes for administrative restore publication."""

from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

from data.bootstrap_catalog import build_bootstrap
from data.catalog_backup import backup_database
from data.incremental_catalog import publish_changes
from data.runtime_catalog import DiskCatalog


class DeliveryReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="delivery-review-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source.sqlite"
        self.target = self.root / "target.sqlite"
        self.bundle = self.root / "backup"
        self.fixture = self.root / "fixture.json"
        self.fixture.write_text(
            '[{"id":"sun","name":"Sun","kind":"star","scale":"solar"}]')
        self.original = build_bootstrap(self.fixture, self.source)

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

    def wait_marker(self, marker, child):
        deadline = time.monotonic() + 20
        while not marker.exists():
            if child.poll() is not None:
                self.fail(str(child.communicate()))
            if time.monotonic() >= deadline:
                self.fail("child failed to reach controlled publication boundary")
            time.sleep(.01)

    def paused_restore(self):
        ready, gate = self.root / "restore-ready", self.root / "restore-gate"
        child = self.process('''
import sys,time
from pathlib import Path
import data.catalog_backup as module
bundle,target,ready,gate=sys.argv[1:]
original=module._copy
def pause(*args):
    Path(ready).touch()
    while not Path(gate).exists(): time.sleep(.01)
    return original(*args)
module._copy=pause
module.restore_database(bundle,target,replace=True)
''', self.bundle, self.target, ready, gate)
        self.wait_marker(ready, child)
        return child, gate

    def assert_success(self, child):
        output, errors = child.communicate(timeout=30)
        self.assertEqual(child.returncode, 0, output + errors)

    def test_patch_waits_for_restore_and_rechecks_expected_revision(self):
        backup_database(self.source, self.bundle)
        self.target.write_bytes(self.source.read_bytes())
        changed = publish_changes(
            self.target, expected_revision=self.original["catalog_revision"],
            upserts=[dict(id="sun", name="Corrected Sun", kind="star", scale="solar")])
        restore, gate = self.paused_restore()
        started = self.root / "writer-started"
        writer = self.process('''
import sys
from pathlib import Path
from data.incremental_catalog import publish_changes,RevisionConflict
target,revision,marker=sys.argv[1:]
Path(marker).touch()
try:
    publish_changes(target,expected_revision=revision,upserts=[dict(id='extra',name='Extra',kind='star',scale='solar')])
except RevisionConflict:
    pass
else:
    raise AssertionError('stale writer overwrote the restored publication')
''', self.target, changed["catalog_revision"], started)
        self.wait_marker(started, writer)
        time.sleep(.1)
        self.assertIsNone(writer.poll(), "writer bypassed restore's publication lock")
        gate.touch()
        self.assert_success(restore)
        self.assert_success(writer)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())

    def test_cold_bootstrap_waits_for_restore_and_keeps_restored_revision(self):
        candidate = self.root / "bootstrap.sqlite"
        build_bootstrap(self.fixture, candidate)
        changed = publish_changes(
            self.source, expected_revision=self.original["catalog_revision"],
            upserts=[dict(id="sun", name="Recovered Sun", kind="star", scale="solar")])
        backup_database(self.source, self.bundle)
        restore, gate = self.paused_restore()
        started = self.root / "initializer-started"
        initializer = self.process('''
import sys
from pathlib import Path
from data.bootstrap_catalog import bootstrap_database
target,bootstrap,marker=sys.argv[1:]
Path(marker).touch()
bootstrap_database(target,bootstrap=bootstrap)
''', self.target, candidate, started)
        self.wait_marker(started, initializer)
        time.sleep(.1)
        self.assertIsNone(initializer.poll(), "initializer bypassed restore's publication lock")
        gate.touch()
        self.assert_success(restore)
        self.assert_success(initializer)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        with DiskCatalog(self.target).snapshot() as snapshot:
            self.assertEqual(snapshot.metadata["catalog_revision"], changed["catalog_revision"])
            self.assertEqual(snapshot.object("sun")["name"], "Recovered Sun")


if __name__ == "__main__":
    unittest.main()
