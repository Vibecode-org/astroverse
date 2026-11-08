"""Bounded-memory build/update benchmark; temporary stress data is self-cleaning.

Run in Docker: python -m tests.benchmark_streaming [--million]
Each builder runs in its own process; Linux ru_maxrss is KiB, including SQLite.
"""
import argparse
import json
from pathlib import Path
import resource
import os
import socket
import statistics
import urllib.request
import urllib.error
import subprocess
import sys
import tempfile
import time


def generate(path, count):
    with path.open('w') as stream:
        stream.write('[')
        for i in range(count):
            row={'id':f'stress_{i:07d}','name':f'Synthetic {i:07d}',
                 'kind':'star' if i%10==0 else 'exoplanet','scale':'local',
                 'source':'synthetic','radius':1,'color':'#aaccee'}
            if i%10:
                row['parent']=f'stress_{i-i%10:07d}'
            else:
                row.update(ra=(i*0.61803398875)%24,dec=(i*0.41421356237)%180-90,distance_ly=1+(i%20000)/100)
            if i: stream.write(',')
            stream.write(json.dumps(row,separators=(',',':')))
        stream.write(']')


def request_measurements(base):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def fetch(path,headers=None):
        start=time.perf_counter()
        with opener.open(urllib.request.Request(base+path,headers=headers or {}),timeout=60) as response:
            body=response.read()
            return body,response.headers,(time.perf_counter()-start)*1000
    near='/api/spatial/v1/nearby?scale=local&frame=equatorial&x=0&y=0&z=0&radius=4'
    sid=json.loads(fetch(near)[0])['sectors'][0]['id']
    paths={'nearby':near,'page512':'/api/spatial/v1/sectors/'+sid,
           'search':'/api/search?q=a','positions':'/api/positions/v1/sectors/solar:verified?at=2026-11-06T12:00:00Z'}
    result={}
    for name,path in paths.items():
        body,headers,first=fetch(path)
        warm=[fetch(path)[2] for _ in range(5)]
        if headers.get('ETag'):
            try:
                fetch(path,{'If-None-Match':headers['ETag']})
                raise AssertionError('expected 304')
            except urllib.error.HTTPError as exc:
                assert exc.code==304
        result[name]={'bytes':len(body),'first_ms':round(first,3),'warm_median_ms':round(statistics.median(warm),3)}
    return {'requests':result,'delivery_peak_kib':int(next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmHWM:')))}


def process_rss(pid):
    return int(next(line.split()[1] for line in Path(f'/proc/{pid}/status').read_text().splitlines() if line.startswith('VmRSS:')))


def measure_server(source,path):
    with socket.socket() as reserve:
        reserve.bind(('127.0.0.1',0)); port=reserve.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={**os.environ,'ASTROVERSE_CATALOG_PATH':str(source.resolve()),'ASTROVERSE_SECTOR_PATH':str(path.resolve())}
    process=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+30
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        while True:
            try:
                with opener.open(base+'/api/health',timeout=1): break
            except (OSError,urllib.error.URLError):
                if time.monotonic()>deadline or process.poll() is not None: raise RuntimeError('benchmark API failed to start')
                time.sleep(.05)
        before=process_rss(process.pid)
        output=subprocess.check_output([sys.executable,'-m','tests.benchmark_streaming','--request-base',base],text=True)
        return {'runtime_before_kib':before,'runtime_after_kib':process_rss(process.pid),**json.loads(output)}
    finally:
        process.terminate();process.wait(timeout=10)


def worker(source):
    from data.streaming_catalog import build_streaming_index
    from data.runtime_catalog import DiskCatalog
    start=time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        path=Path(tmp)/'runtime.sqlite'
        from backend.prepare_runtime import signature
        meta=build_streaming_index(path,source,source_signature=signature(source))
        seconds=time.perf_counter()-start
        build_peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        with DiskCatalog(path).snapshot() as index:
            page=list(index.select(limit=512))
            binary_bytes=sum(map(len,index.binary('v2')))
            sectors=index.nearby('local','equatorial',(0,0,0),4,limit=128)
        measured=measure_server(source,path)
        return {'count':meta['object_count'],**measured,'build_seconds':seconds,'builder_peak_kib':build_peak,
                'sqlite_bytes':path.stat().st_size,'legacy_v2_bytes':binary_bytes,
                'nearby_sectors':len(sectors),'page_objects':len(page),
                'end_peak_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',type=Path)
    parser.add_argument('--request-base')
    parser.add_argument('--million',action='store_true')
    args=parser.parse_args()
    if args.request_base:
        print(json.dumps(request_measurements(args.request_base)),flush=True)
        return
    if args.worker:
        print(json.dumps(worker(args.worker)),flush=True)
        return
    sources=[Path('data/catalog_seed.json')]
    with tempfile.TemporaryDirectory() as tmp:
        for count in ([100000,1000000] if args.million else [100000]):
            path=Path(tmp)/f'synthetic_{count}.json'
            generate(path,count)
            sources.append(path)
        for source in sources:
            subprocess.run([sys.executable,'-m','tests.benchmark_streaming','--worker',str(source)],check=True)

if __name__=='__main__':
    main()
