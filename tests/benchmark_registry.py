"""Isolated sources/positions HTTP timing and Linux RSS. No retained artifacts.

Docker: python -m tests.benchmark_registry
The synthetic allocation probe is metadata only, never real astronomical data.
"""
import argparse
import json
from pathlib import Path
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
import urllib.error


def rss(pid):
    return int(next(line.split()[1] for line in Path(f'/proc/{pid}/status').read_text().splitlines() if line.startswith('VmRSS:')))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--serve',type=int);args=parser.parse_args()
    if args.serve:
        from fastapi import FastAPI
        from backend.position_api import install_position_api
        import uvicorn
        app=FastAPI();install_position_api(app,lambda supplied,etag:supplied==etag)
        uvicorn.run(app,host='127.0.0.1',port=args.serve,log_level='error')
        return
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
    process=subprocess.Popen([sys.executable,'-m','tests.benchmark_registry','--serve',str(port)],stdout=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+30
        while True:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError('benchmark API failed to start')
                time.sleep(.05)
        before=rss(process.pid)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        result={}
        for name,path in [('registry5','/api/sources/v1/objects?limit=128'),
                          ('registry2','/api/sources/v1/objects?limit=2'),
                          ('positions5','/api/positions/v1/sectors/solar:verified?jd_tdb=2451545')]:
            times=[]
            for _ in range(6):
                start=time.perf_counter()
                with opener.open(f'http://127.0.0.1:{port}'+path) as response:
                    body=response.read();etag=response.headers['ETag']
                times.append((time.perf_counter()-start)*1000)
            try:
                opener.open(urllib.request.Request(f'http://127.0.0.1:{port}'+path,headers={'If-None-Match':etag}))
                raise AssertionError('expected 304')
            except urllib.error.HTTPError as error:
                assert error.code==304 and error.read()==b''
            result[name]={'bytes':len(body),'first_ms':round(times[0],3),
                'median5_ms':round(statistics.median(times[1:]),3),'api_rss_kib':rss(process.pid)}
        from data.source_registry import SourceRegistry, MODEL, REGISTRY
        import tracemalloc
        tracemalloc.start()
        registry=SourceRegistry([MODEL],REGISTRY.page()['objects'])
        allocated,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
        assert len(registry.targets)==5
        result.update(api_before_kib=before,registry5_allocation_bytes=allocated,registry5_construction_peak_bytes=peak,
            client_peak_kib=int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:'))))
        print(json.dumps(result,indent=2))
    finally:
        process.terminate();process.wait(timeout=10)


if __name__=='__main__':main()
