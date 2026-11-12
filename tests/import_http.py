"""Production uvicorn/TCP acceptance for a directly published SQLite catalog."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


@contextmanager
def api(path):
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1', 0))
        port = reserve.getsockname()[1]
    env = {**os.environ, 'ASTROVERSE_CATALOG_MODE': 'published', 'ASTROVERSE_SECTOR_PATH': str(path),
           'ASTROVERSE_CATALOG_PATH': str(path.parent/'does-not-exist.json')}
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1',
                                '--port', str(port), '--log-level', 'error'], env=env)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(route, headers=None):
        try:
            response = opener.open(urllib.request.Request(f'http://127.0.0.1:{port}'+route, headers=headers or {}), timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read(3*1024**2)
            return response.code, json.loads(body) if body else None, response.headers
    try:
        deadline = time.monotonic()+30
        while True:
            try:
                if get('/api/health')[0] == 200:
                    break
            except OSError:
                pass
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('published API failed to start')
            time.sleep(.05)
        yield get
    finally:
        process.terminate()
        process.wait(timeout=10)


def checks(get, count):
    assert get('/api/health')[1]['objects'] == count
    card = get('/api/objects/sbdb:a:0')[1]
    assert card['source_id'] == '0' and card['source_epoch'] is None
    assert get('/api/search?q=Synthetic%20asteroid%200000000')[1][0]['id'] == 'sbdb:a:0'
    route = '/api/spatial/v1/sectors/solar:system?limit=2'
    status, page, headers = get(route)
    assert status == 200 and len(page['objects']) == 2
    revision = headers['X-Catalog-Snapshot']
    assert get(route, {'If-None-Match': headers['ETag']})[0] == 304
    assert get(route+'&snapshot='+'0'*64, {'If-None-Match': headers['ETag']})[0] == 409
    assert page['next_after']
    following = get(route+'&snapshot='+revision+'&after='+urllib.parse.quote(page['next_after']))[1]
    assert following['objects'][0]['object']['id'] > page['objects'][-1]['object']['id']
    assert get('/api/spatial/v1/objects/sbdb:a:0/sector')[0] == 200
    return {'health': count, 'card': True, 'search': True, 'page': True, 'etag304': True, 'revision409': True}


def check_catalog_http(path, count):
    with api(path) as get:
        return checks(get, count)
