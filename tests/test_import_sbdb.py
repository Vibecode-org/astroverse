import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import ijson
from data.import_sbdb import import_sbdb, SourceError, normalize, validate_staged
from data.incremental_catalog import RevisionConflict
from data.runtime_catalog import DiskCatalog
from data.streaming_catalog import build_streaming_index
from tests.sbdb_fixture import serve


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'catalog.sqlite'
        build_streaming_index(self.path, None, objects=iter([dict(id='sun', name='Sun', kind='star', scale='solar')]))

    def revision(self):
        return DiskCatalog(self.path).snapshot()

    def run_import(self, url, **kwargs):
        with self.revision() as snap:
            rev = snap.metadata['catalog_revision']
        return import_sbdb(self.path, expected_revision=rev, url=url, limit=3, mode='fixture', **kwargs)

    def test_repeat_changed_and_explicit_delete_old_reader(self):
        with serve() as (url, _):
            first = self.run_import(url)
            before = self.path.read_bytes()
            second = self.run_import(url, expected_sha256=first['input']['sha256'])
            self.assertFalse(second['changed'])
            self.assertEqual(self.path.read_bytes(), before)
        with self.revision() as old, serve(change=1) as (url, _):
            changed = self.run_import(url)
            self.assertTrue(changed['changed'])
            self.assertEqual(old.object('sbdb:a:1')['radius_km'], .5)
            with self.revision() as new:
                self.assertEqual(new.object('sbdb:a:1')['radius_km'], 1)
        with serve(1) as (url, _):
            self.run_import(url)
            with self.revision() as snap:
                self.assertIsNotNone(snap.object('sbdb:a:2'))
            result = self.run_import(url, deletes=['sbdb:a:2'])
            self.assertEqual(result['metadata']['object_count'], 3)
            for oid in ['sun', 'missing', 'sbdb:a:0']:
                with self.assertRaises(ValueError):
                    self.run_import(url, deletes=[oid])

    def test_failures_preserve_active_and_clean_staging(self):
        before = self.path.read_bytes()
        for fault in ['cut', 'bad', 'duplicate', 'wide', '400', 'length', 'redirect']:
            with self.subTest(fault=fault), serve(fault=fault) as (url, _):
                with self.assertRaises((ValueError, SourceError, ijson.JSONError)):
                    self.run_import(url)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertFalse(list(self.path.parent.glob('.catalog.sqlite.import-*')))
        with serve() as (url, _):
            for options in [{'max_bytes': 30}, {'expected_sha256': '0'*64}]:
                with self.assertRaises(SourceError):
                    self.run_import(url, **options)
            for operation in ['data.import_sbdb.validate_staged', 'pathlib.Path.replace']:
                with patch(operation, side_effect=OSError('injected publication failure')):
                    with self.assertRaises(OSError):
                        self.run_import(url)
                self.assertEqual(self.path.read_bytes(), before)

    def test_bounded_retries_and_timeout_real_http(self):
        for fault, attempts in [('503', 2), ('400', 1), ('timeout', 2)]:
            with serve(fault=fault) as (url, handler), patch('data.import_sbdb.retry_sleep'):
                with self.assertRaises(SourceError):
                    self.run_import(url, timeout=.03, retries=1)
                self.assertEqual(handler.attempts, attempts)

    def test_concurrent_writers_and_orphan_recovery(self):
        with self.revision() as snap:
            rev = snap.metadata['catalog_revision']
        orphan = self.path.parent/'.catalog.sqlite.import-interrupted'
        orphan.mkdir()
        (orphan/'partial.sqlite').write_bytes(b'broken')
        with serve() as (url, handler), ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(import_sbdb, self.path, expected_revision=rev, url=url, limit=3) for _ in range(2)]
            results = []
            for future in futures:
                try:
                    results.append(future.result()['changed'])
                except RevisionConflict:
                    results.append('conflict')
            self.assertCountEqual(results, [True, 'conflict'])
            self.assertEqual(handler.attempts, 1)
        self.assertFalse(orphan.exists())

    def test_direct_generator_has_json_validation_and_graph_checks(self):
        before = self.path.read_bytes()
        base = dict(id='a', name='A', kind='star', scale='local')
        for rows in [[dict(base, radius=-1)], [dict(base, parent='missing')],
                     [dict(base, parent='b'), dict(base, id='b', parent='a')], [base, base]]:
            with self.assertRaises(ValueError):
                build_streaming_index(self.path, None, objects=iter(rows))
            self.assertEqual(self.path.read_bytes(), before)

    def test_sigkill_and_restart_never_resume_mixed_input(self):
        before = self.path.read_bytes()
        with self.revision() as snap:
            rev = snap.metadata['catalog_revision']
        with serve(fault='hang') as (url, handler):
            process = subprocess.Popen([sys.executable, '-m', 'data.import_sbdb', str(self.path),
                '--expected-revision', rev, '--url', url, '--limit', '3'], stdout=subprocess.DEVNULL)
            try:
                deadline = time.monotonic()+5
                while handler.attempts == 0:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(.01)
                process.kill()
                process.wait(timeout=5)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(list(self.path.parent.glob('.catalog.sqlite.import-*')))
        with serve(change=1) as (url, _):
            self.run_import(url)
        self.assertFalse(list(self.path.parent.glob('.catalog.sqlite.import-*')))
        with self.revision() as snap:
            self.assertEqual(snap.object('sbdb:a:1')['radius_km'], 1)

    def test_legacy_identity_preserves_id_and_visuals_and_rejects_ambiguity(self):
        base = [dict(id='sun', name='Sun', kind='star', scale='solar'),
                dict(id='legacy', name='Synthetic asteroid 0000000', kind='asteroid', scale='solar',
                     source='NASA JPL SBDB', radius=3, color='#abcdef')]
        build_streaming_index(self.path, None, objects=iter(base))
        with serve(1) as (url, _):
            self.run_import(url)
        with self.revision() as snap:
            self.assertIsNone(snap.object('sbdb:a:0'))
            self.assertEqual(snap.object('legacy')['radius'], 3)
            self.assertEqual(snap.object('legacy')['source_id'], '0')
            self.assertEqual(len(snap.object('legacy')['input_sha256']), 64)
        for field in ['source_id', 'name']:
            rows = [base[0], dict(base[1], source_id='0'), dict(base[1], id='other', source_id='0')]
            if field == 'name':
                for obj in rows[1:]:
                    obj.pop('source_id')
            build_streaming_index(self.path, None, objects=iter(rows))
            with serve(1) as (url, _), self.assertRaises(SourceError):
                self.run_import(url)

    def test_http_envelope_validation_and_budget_configuration(self):
        valid = {'signature': {'source': 'NASA/JPL SBDB Query API', 'version': '1.0'},
                 'count': '1', 'fields': ['full_name', 'pdes', 'a', 'per', 'diameter'],
                 'data': [['Body 1', '1', None, None, None]]}
        cases = [[], {'fields': []}]
        for field, value in [('signature', {}), ('count', True), ('count', '2'), ('fields', []),
                             ('data', [['Body', '1']]), ('data', [[{}]*5]),
                             ('data', [['', '1', None, None, None]]),
                             ('data', [['Body', 'X'*129, None, None, None]]),
                             ('data', [['Body', '1', 'bad', None, None]]),
                             ('unexpected', 1), ('signature', {'x': list(range(80))})]:
            cases.append(dict(valid, **{field: value}))
        before = self.path.read_bytes()
        for case in cases:
            with self.subTest(case=case), serve(body=json.dumps(case).encode()) as (url, _):
                with self.assertRaises((SourceError, ijson.JSONError)):
                    self.run_import(url)
                self.assertEqual(self.path.read_bytes(), before)
        with serve(body=json.dumps(valid).encode()) as (url, _):
            self.run_import(url)
            with self.revision() as snap:
                self.assertIsNone(snap.object('sbdb:a:1')['radius_km'])
            for options in [{'retries': 4}, {'max_bytes': 0}, {'timeout': 0}, {'total_timeout': 0}]:
                with self.assertRaises(ValueError):
                    self.run_import(url, **options)
            for endpoint in ['file:///tmp/no', url+'?query=x']:
                with self.assertRaises(ValueError):
                    self.run_import(endpoint)
        from data.import_sbdb import BoundedReader
        from io import BytesIO
        with self.assertRaises(TimeoutError):
            BoundedReader(BytesIO(b'{}'), 100, -1).read(1)
        for payload in [b'[[[[[0]]]]]', b'1'*5000, b'"'+b'x'*5000+b'"']:
            with self.assertRaises(SourceError):
                BoundedReader(BytesIO(payload), 10000, time.monotonic()+1).read()

    def test_cli_and_published_startup_do_not_require_json(self):
        from data.import_sbdb import main
        from backend.prepare_runtime import ensure_runtime
        from backend import entrypoint
        from io import StringIO
        with self.revision() as snap:
            rev = snap.metadata['catalog_revision']
        with serve(1) as (url, _), patch.object(sys, 'argv', ['import_sbdb', str(self.path),
                '--expected-revision', rev, '--url', url, '--limit', '1']), patch('sys.stdout', new_callable=StringIO) as output:
            main()
            self.assertTrue(json.loads(output.getvalue())['changed'])
            with self.assertRaises(SystemExit) as exc:
                main()
            self.assertEqual(exc.exception.code, 1)
        with patch.dict(os.environ, {'ASTROVERSE_CATALOG_MODE': 'published', 'ASTROVERSE_SECTOR_PATH': str(self.path)}):
            self.assertEqual(ensure_runtime(self.path.parent/'missing.json'), self.path)
            with patch.object(sys, 'argv', ['entrypoint', 'uvicorn', 'backend.app:app']), patch.object(os, 'execvp') as execute:
                entrypoint.main()
                execute.assert_called_once()
        with patch.dict(os.environ, {'ASTROVERSE_CATALOG_MODE': 'published', 'ASTROVERSE_SECTOR_PATH': ''}):
            with self.assertRaises(ValueError):
                ensure_runtime(self.path.parent/'missing.json')
        for opts in [{'limit': 0}, {'retries': 4}, {'mode': 'bad'}]:
            with self.assertRaises(ValueError):
                import_sbdb(self.path, expected_revision=rev, **opts)

    def test_corrupt_candidate_is_rejected_before_publication(self):
        original = build_streaming_index
        before = self.path.read_bytes()
        for corruption in ["UPDATE objects SET payload='{}' WHERE id='sun'",
                           "UPDATE metadata SET value='999' WHERE key='object_count'",
                           "UPDATE sectors SET object_count=999",
                           "DELETE FROM representations WHERE name='v1'",
                           "INSERT INTO sector_bounds VALUES (999,0,1,0,1,0,1)"]:
            def corrupt(path, *args, **kwargs):
                result = original(path, *args, **kwargs)
                with sqlite3.connect(path) as db:
                    db.execute(corruption)
                return result
            with serve(1) as (url, _), patch('data.import_sbdb.build_streaming_index', side_effect=corrupt):
                with self.assertRaises(ValueError):
                    self.run_import(url)
            self.assertEqual(self.path.read_bytes(), before)

    def test_real_seed_catalog_and_existing_sbdb_id_roundtrip(self):
        source = Path(__file__).parents[1]/'data/catalog_seed.json'
        meta = build_streaming_index(self.path, source)
        payload = {'signature': {'source': 'NASA/JPL SBDB Query API', 'version': '1.0'},
                   'count': '1', 'fields': ['full_name', 'pdes', 'a', 'per', 'diameter'],
                   'data': [['1 Ceres (A801 AA)', '1', '2.77', '1680', '939.4']]}
        with serve(body=json.dumps(payload).encode()) as (url, _):
            result = self.run_import(url)
        self.assertEqual(result['metadata']['object_count'], meta['object_count'])
        with self.revision() as snap:
            self.assertIsNone(snap.object('sbdb:a:1'))
            self.assertEqual(snap.object('1_ceres')['source_id'], '1')
            self.assertEqual(snap.object('1_ceres')['radius_km'], 469.7)
            self.assertEqual(snap.object('1_ceres')['texture'], 'rocky')

    def test_cleanup_failure_after_commit_is_recovered_next_import(self):
        original_unlink = os.unlink
        def denied(path, *args, **kwargs):
            if str(path).endswith('source.sqlite'):
                raise PermissionError('injected cleanup failure')
            return original_unlink(path, *args, **kwargs)
        with serve(1) as (url, _), patch('os.unlink', side_effect=denied):
            result = self.run_import(url)
        self.assertTrue(result['changed'])
        self.assertTrue(list(self.path.parent.glob('.catalog.sqlite.import-*')))
        with serve(1) as (url, _):
            self.assertFalse(self.run_import(url)['changed'])
        self.assertFalse(list(self.path.parent.glob('.catalog.sqlite.import-*')))
