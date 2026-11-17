"""Production temporal routes against isolated synthetic SQLite publications."""
from pathlib import Path
import json
import sqlite3
import time
from threading import Event
from unittest.mock import patch
import tempfile
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.position_api import install_position_api
from data.temporal_index import TemporalIndex, TemporalSnapshot, build_synthetic, ensure_real, EPOCH_JD


class TemporalAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'index.sqlite'
        build_synthetic(self.path, 2304)
        self.app = FastAPI()
        install_position_api(self.app, lambda supplied, etag: supplied is not None and
                             (supplied == '*' or etag in supplied),
                             temporal_index_factory=lambda: TemporalIndex(self.path))
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.query = dict(anchor='synthetic-0000000', dx=0, dy=0, dz=0, radius=100000,
                          ox=0, oy=0, oz=0, jd_tdb=EPOCH_JD)

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def test_shared_contract_bounded_manifest_sector_and_conditional_requests(self):
        contract = self.client.get('/api/positions/v1/contract').json()
        self.assertTrue(contract['synthetic'])
        self.assertEqual(contract['temporal_selection']['max_candidate_members'],2048)
        result = self.client.get('/api/positions/v1/nearby',params=self.query)
        self.assertEqual(result.status_code,200,result.text)
        self.assertTrue(result.headers['server-timing'].startswith('temporal;dur='))
        body = result.json()
        self.assertEqual(len(body['sectors']),16)
        self.assertEqual(body['objects'],[])
        for validator in ('*','W/'+result.headers['etag'],'"other", '+result.headers['etag']):
            self.assertEqual(self.client.get('/api/positions/v1/nearby',params=self.query,
                                           headers={'If-None-Match':validator}).status_code,304)
        query = {'jd_tdb':EPOCH_JD,'revision':body['revision'],'temporal_revision':body['temporal_revision']}
        response = self.client.get('/api/positions/v1/sectors/temporal:0000000',params=query)
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.headers['server-timing'].startswith('positions;dur='))
        frame = response.json()
        self.assertEqual(len(frame['objects']),128)
        self.assertIsNone(frame['objects'][-1]['position'])
        self.assertEqual(frame['objects'][0]['position'],[-63500,0,-3500])
        self.assertLess(len(response.content),256*1024)
        self.assertEqual(frame['hierarchy']['jd_tdb'],EPOCH_JD)
        changed = self.client.get('/api/positions/v1/sectors/temporal:0000000',params={**query,'jd_tdb':EPOCH_JD+1})
        self.assertNotEqual(changed.headers['etag'],response.headers['etag'])
        self.assertEqual(changed.json()['objects'][0]['position'],[-63400,-10,-3500])
        source = self.client.get('/api/sources/v1/objects?limit=128').json()
        self.assertEqual(len(source['objects']),128)
        self.assertEqual(source['next_offset'],128)

    def test_overflow_empty_unknown_invalid_time_and_revision_before_304(self):
        for changes, expected in (({'radius':1e12},413),({'dy':1e9},200),
                                  ({'radius':-1},422),({'jd_tdb':0},422),({'ox':None},422),
                                  ({'anchor':'missing'},422),({'revision':'old'},409),
                                  ({'temporal_revision':'old'},409)):
            params={key:value for key,value in {**self.query,**changes}.items() if value is not None}
            response=self.client.get('/api/positions/v1/nearby',params=params,headers={'If-None-Match':'*'})
            # Empty valid representation still supports conditional reads.
            self.assertEqual(response.status_code,304 if changes=={'dy':1e9} else expected,response.text)
        empty=self.client.get('/api/positions/v1/nearby',params={**self.query,'dy':1e9}).json()
        self.assertEqual(empty['sectors'],[])
        self.assertEqual(self.client.get('/api/positions/v1/sectors/missing',params={'jd_tdb':EPOCH_JD}).status_code,404)
        unknown=self.client.get('/api/positions/v1/objects/missing',params={'jd_tdb':EPOCH_JD}).json()
        self.assertIsNone(unknown['objects'][0]['position'])
        self.assertEqual(self.client.get('/api/positions/v1/objects/synthetic-0000127',params={'jd_tdb':EPOCH_JD}).json()['objects'][0]['position'],None)

    def test_publication_conflict_and_missing_or_corrupt_index_fail_closed(self):
        old=self.client.get('/api/positions/v1/nearby',params=self.query).json()
        build_synthetic(self.path,2305)
        response=self.client.get('/api/positions/v1/sectors/temporal:0000000',params={
            'jd_tdb':EPOCH_JD,'revision':old['revision'],'temporal_revision':old['temporal_revision']},headers={'If-None-Match':'*'})
        self.assertEqual(response.status_code,409,response.text)
        self.path.unlink()
        response=self.client.get('/api/positions/v1/nearby',params=self.query,headers={'If-None-Match':'*'})
        self.assertEqual(response.status_code,503,response.text)
        self.path.write_bytes(b'corrupt')
        self.assertEqual(self.client.get('/api/positions/v1/nearby',params=self.query).status_code,503)
        self.assertEqual(self.client.get('/api/positions/v1/contract').status_code,503)

    def test_narrow_publication_interval_applies_to_every_route_before_validators(self):
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE metadata SET value=? WHERE key=?', (json.dumps([EPOCH_JD,EPOCH_JD+4]),'interval'))
        for jd in (EPOCH_JD-1,EPOCH_JD+4,EPOCH_JD+5):
            for path in ('nearby','sectors/temporal:0000000','objects/synthetic-0000000'):
                params={**self.query,'jd_tdb':jd} if path=='nearby' else {'jd_tdb':jd}
                response=self.client.get('/api/positions/v1/'+path,params=params,headers={'If-None-Match':'*'})
                self.assertEqual(response.status_code,422,response.text)
                self.assertEqual(response.json()['detail']['code'],'unsupported_simulation_time')

    def test_synthetic_source_revision_can_pin_paging(self):
        first=self.client.get('/api/sources/v1/objects?limit=2').json()
        second=self.client.get('/api/sources/v1/objects',params={'limit':2,'offset':first['next_offset'],'revision':first['revision']})
        self.assertEqual(second.status_code,200,second.text)
        self.assertNotEqual(first['objects'][0]['id'],second.json()['objects'][0]['id'])
        conflict=self.client.get('/api/sources/v1/objects',params={'revision':'old'},headers={'If-None-Match':'*'})
        self.assertEqual(conflict.status_code,409)

    def test_corrupt_model_membership_and_candidate_counts_fail_closed(self):
        original=self.path.read_bytes()
        mutations=[
            ("UPDATE metadata SET value='-1' WHERE key='count'",'sectors/temporal:0000000',503),
            ("UPDATE metadata SET value='99' WHERE key='schema'",'sectors/temporal:0000000',503),
            ("UPDATE metadata SET value='0' WHERE key='bucket_days'",'sectors/temporal:0000000',503),
            ("DROP TABLE bounds",'sectors/temporal:0000000',503),
            ("UPDATE sectors SET object_count=-1 WHERE id='temporal:0000000'",'nearby',503),
            ("UPDATE sectors SET object_count=-1 WHERE id='temporal:0000000'",'sectors/temporal:0000000',503),
            ("UPDATE sectors SET object_count=127 WHERE id='temporal:0000000'",'sectors/temporal:0000000',503),
            ("UPDATE sectors SET object_count=129 WHERE id='temporal:0000000'",'sectors/temporal:0000000',413),
        ]
        for sql,path,status in mutations:
            with self.subTest(sql=sql,path=path):
                self.path.write_bytes(original)
                with sqlite3.connect(self.path) as db:db.execute(sql)
                response=self.client.get('/api/positions/v1/'+path,params=self.query if path=='nearby' else {'jd_tdb':EPOCH_JD},headers={'If-None-Match':'*'})
                self.assertEqual(response.status_code,status,response.text)
        self.path.write_bytes(original)
        with sqlite3.connect(self.path) as db:
            db.executemany('INSERT INTO metadata VALUES (?,?)',[(f'excess-{n}','null') for n in range(33)])
        self.assertEqual(self.client.get('/api/positions/v1/contract').status_code,503)
        self.assertEqual(self.client.get('/api/sources/v1/objects').status_code,503)
        self.path.write_bytes(original)
        with sqlite3.connect(self.path) as db:
            model=json.loads(db.execute("SELECT value FROM metadata WHERE key='coordinates'").fetchone()[0])
            model['unit']='ly'
            db.execute("UPDATE metadata SET value=? WHERE key='coordinates'",(json.dumps(model),))
        self.assertEqual(self.client.get('/api/positions/v1/contract').status_code,503)

    def test_byte_limit_invalid_identifiers_and_unknown_anchor_before_validators(self):
        with patch('backend.temporal_api.MAX_BYTES',1):
            self.assertEqual(self.client.get('/api/positions/v1/nearby',params=self.query,headers={'If-None-Match':'*'}).status_code,413)
        query={key:value for key,value in self.query.items() if key not in ('ox','oy','oz')}
        response=self.client.get('/api/positions/v1/nearby',params={**query,'anchor':'synthetic-0000127'})
        self.assertEqual(response.status_code,422)
        self.assertEqual(self.client.get('/api/positions/v1/sectors/'+'x'*257,params={'jd_tdb':EPOCH_JD}).status_code,422)
        self.assertEqual(self.client.get('/api/positions/v1/objects/'+'x'*513,params={'jd_tdb':EPOCH_JD}).status_code,422)

    def test_real_solver_mismatch_and_solver_failure_are_explicit(self):
        class ControlledEngine:
            def __init__(self, mode):self.mode=mode
            def evaluate(self,**kwargs):
                if self.mode=='error':raise ValueError('controlled invalid solver input')
                return {'revision':'wrong','registry_revision':'wrong'}
            def close(self):pass
        for mode,expected in [('error',422),('mismatch',503)]:
            app=FastAPI()
            install_position_api(app,lambda a,b:a=='*',engine_factory=lambda:ControlledEngine(mode),
                                 temporal_index_factory=lambda:ensure_real(Path(self.temp.name)/'real.sqlite'))
            with TestClient(app) as client:
                response=client.get('/api/positions/v1/sectors/solar:verified',params={'jd_tdb':EPOCH_JD},headers={'If-None-Match':'*'})
                self.assertEqual(response.status_code,expected,response.text)
        with self.assertRaises(ValueError):ensure_real(self.path)

    def test_timed_out_synthetic_worker_retains_slot_until_cooperative_return(self):
        app=FastAPI()
        install_position_api(app,lambda a,b:a==b,temporal_index_factory=lambda:TemporalIndex(self.path),
                             work_limits={'workers':1,'timeout':.02,'poll':.005})
        finish=Event();entered=Event();original=TemporalSnapshot.positions
        def slow(snapshot,rows,jd):
            entered.set();finish.wait(2)
            return original(snapshot,rows,jd)
        with TestClient(app) as client,patch.object(TemporalSnapshot,'positions',slow):
            try:
                response=client.get('/api/positions/v1/sectors/temporal:0000000',params={'jd_tdb':EPOCH_JD})
                self.assertTrue(entered.is_set())
                self.assertEqual(response.status_code,503)
                self.assertEqual(response.json()['detail']['code'],'position_timeout')
                self.assertEqual(app.state.position_work.inspect()['active'],1)
                busy=client.get('/api/positions/v1/sectors/temporal:0000000',params={'jd_tdb':EPOCH_JD})
                self.assertEqual(busy.json()['detail']['code'],'position_busy')
            finally:finish.set()
            deadline=time.monotonic()+2
            while app.state.position_work.inspect()['active'] and time.monotonic()<deadline:time.sleep(.005)
            self.assertEqual(app.state.position_work.inspect()['active'],0)
            self.assertEqual(client.get('/api/positions/v1/sectors/temporal:0000000',params={'jd_tdb':EPOCH_JD}).status_code,200)
