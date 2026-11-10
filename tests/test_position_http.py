"""Real HTTP disconnect/deadline/admission using production API and offline BSP."""
import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from fastapi import FastAPI
import uvicorn
from backend.position_api import install_position_api
from data.ephemeris import Ephemeris


class SlowEngine:
    def __init__(self):
        self.inner=Ephemeris()
        self.finish=threading.Event()
        self.entered=threading.Event()
        self.calls=0
        self.block=True

    def evaluate(self, **kwargs):
        self.calls+=1
        if self.block:
            self.entered.set()
            self.finish.wait(3)
        return self.inner.evaluate(**kwargs)

    def close(self):self.inner.close()


class PositionHTTPTests(unittest.TestCase):
    def test_deadline_disconnect_bounded_slots_and_recovery(self):
        engine=SlowEngine();app=FastAPI()
        install_position_api(app,lambda a,b:a==b,engine_factory=lambda:engine,
                             work_limits={'workers':2,'timeout':.15,'poll':.005})
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='on'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        path='/api/positions/v1/sectors/solar:verified?at=2027-01-01T00:00:00Z'
        def get(headers=None):
            try:
                with opener.open(urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers=headers or {}),timeout=2) as response:
                    return response.status,json.loads(response.read()),response.headers
            except urllib.error.HTTPError as error:return error.code,json.loads(error.read()),error.headers
        try:
            deadline=time.monotonic()+5
            while not server.started:
                if time.monotonic()>deadline:self.fail('HTTP server startup timed out')
                time.sleep(.005)
            # Disconnect while the first worker is executing a native operation.
            connection=socket.create_connection(('127.0.0.1',port),timeout=1)
            connection.sendall(f'GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n'.encode())
            self.assertTrue(engine.entered.wait(1));connection.close();time.sleep(.03)
            # Second admitted slot waits for the engine lock, then times out.
            started=time.monotonic();status,body,headers=get()
            self.assertEqual(status,503);self.assertEqual(body['detail']['code'],'position_timeout')
            self.assertLess(time.monotonic()-started,1)
            # The waiting cooperative worker exits; one uninterruptible worker
            # remains charged. Repeated deadlines cannot enqueue native solvers.
            for _ in range(5):
                status,body,_=get()
                self.assertEqual(status,503)
                self.assertIn(body['detail']['code'],['position_timeout','position_busy'])
            self.assertEqual(engine.calls,1)
            engine.block=False;engine.finish.set();time.sleep(.03)
            trace={'X-Astroverse-Client':'http-test','X-Astroverse-Selection':'http-test.1.0','X-Astroverse-Request':'http-test.1'}
            status,frame,headers=get(trace)
            self.assertEqual(status,200);self.assertEqual(len(frame['objects']),5)
            self.assertEqual(engine.calls,2)  # Cancelled work never supplied this cache hit.
            self.assertTrue(frame['evaluated_at'].startswith('2027-01-01'))
            self.assertEqual(headers['X-Astroverse-Request'],'http-test.1')
            status,_,headers=get({'X-Astroverse-Request':'x'*129})
            self.assertEqual(status,200);self.assertNotEqual(headers['X-Astroverse-Request'],'x'*129)
        finally:
            engine.finish.set();server.should_exit=True;thread.join(timeout=5);sock.close()
            self.assertFalse(thread.is_alive())
