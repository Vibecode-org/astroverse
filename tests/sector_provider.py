"""Isolated synthetic positions HTTP fixture. NEVER imported by production.

Run only with docker-compose.sectors-test.yml. No BSP, catalog or real bodies.
32 independently delayed sectors, 64 artificial centers each, plus unknowns.
"""
import asyncio
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from skyfield.api import load

app = FastAPI(title='Astroverse synthetic sector fixture')
timescale = load.timescale(builtin=True)
state = {'revision':1, 'delay':200, 'fail':'', 'conflict':0, 'hang':'', 'mixed':''}
metrics = {'requests':0, 'active':0, 'peak_active':0, 'bytes':0, 'max_bytes':0,
           'statuses':{}, 'total_ms':0, 'max_ms':0}
traces = deque(maxlen=4096)


def current_revision():
    return f'synthetic-sectors-{state["revision"]}'


def metadata(at):
    from data.ephemeris import parse_utc, UTC_START, UTC_STOP
    try:
        date = parse_utc(at)
    except ValueError as exc:
        raise HTTPException(422, detail={'message':str(exc)}) from exc
    return {'version':'positions/1', 'revision':current_revision(), 'registry_revision':'synthetic-registry',
            'evaluated_at':date.isoformat(), 'jd_tdb':float(timescale.from_datetime(date).tdb),
            'source':'synthetic HTTP fixture; no measured astronomy',
            'coordinates':{'representation':'simulation_position', 'unit':'km', 'reference_system':'ICRF',
                           'origin':'solar_system_barycenter', 'time_scale':'TDB', 'corrections':'NONE',
                           'revision':current_revision(), 'accuracy':None,
                           'utc_interval':[UTC_START.isoformat(),UTC_STOP.isoformat()]}, 'objects':[]}


def payload(at, sector):
    result = metadata(at)
    number = int(sector.rsplit(':',1)[1]); origin = [number*6000000,0,0]
    # A deterministic, explicitly artificial function of time, no orbit claim.
    shift = (datetime.fromisoformat(at.replace('Z','+00:00')).timestamp() % 86400) / 100
    objects = [{'id':f'synthetic-{number*64+i:03}', 'status':'computed',
                'source':'synthetic', 'position':[origin[0]+i*1000,shift,i*500]} for i in range(63)]
    objects.append({'id':f'synthetic-{number*64+63:03}', 'status':'unknown', 'source':'synthetic', 'position':None})
    result.update(sector=sector, objects=objects)
    result['hierarchy'] = {'version':'physical-hierarchy/1', 'revision':result['revision'],
        'evaluated_at':result['evaluated_at'], 'jd_tdb':result['jd_tdb'],
        **{key:result['coordinates'][key] for key in ['reference_system','origin','unit','time_scale']},
        'sectors':[{'id':sector,'origin_km':origin}],
        'systems':[{'id':sector+':system','sector_id':sector,'offset_km':[0,0,0]}],
        'bodies':[{'id':row['id'],'system_id':sector+':system' if row['position'] else None,
                   'offset_km':[i*1000,shift,i*500] if row['position'] else None} for i,row in enumerate(objects)]}
    return result


@app.middleware('http')
async def measure(request, call_next):
    if not request.url.path.startswith('/api/positions/'):
        return await call_next(request)
    metrics['requests'] += 1; metrics['active'] += 1
    record = {'client':request.headers.get('x-astroverse-client'),
              'selection':request.headers.get('x-astroverse-selection'),
              'request':request.headers.get('x-astroverse-request'),
              'path':request.url.path,'at':request.query_params.get('at'),
              'anchor':request.query_params.get('anchor'),'status':None}
    traces.append(record)
    metrics['peak_active'] = max(metrics['peak_active'],metrics['active']); start = time.perf_counter()
    try:
        response = await call_next(request)
        status = str(response.status_code)
        record['status'] = response.status_code
        metrics['statuses'][status] = metrics['statuses'].get(status,0)+1
        size = int(response.headers.get('content-length',0))
        metrics['bytes'] += size; metrics['max_bytes'] = max(metrics['max_bytes'],size)
        return response
    finally:
        elapsed = (time.perf_counter()-start)*1000
        record['ms'] = round(elapsed,3)
        metrics['total_ms'] += elapsed; metrics['max_ms'] = max(metrics['max_ms'],elapsed); metrics['active'] -= 1


@app.get('/api/health')
def health():
    return {'status':'ok','objects':0,'synthetic':True}


@app.post('/api/_test/control')
async def control(request: Request):
    values = await request.json()
    for key,value in values.items():
        if key not in state:
            raise HTTPException(422,'Unknown fixture control')
        state[key] = value
    return state


@app.get('/api/_test/metrics')
def measurements():
    rss = next(int(line.split()[1]) for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('VmRSS:'))
    return {**metrics,'traces':list(traces),'provider_rss_kib':rss,'builder':'none; generated per bounded request'}


@app.get('/api/sources/v1/objects')
def sources(limit: int=128, q: str=''):
    objects = [{'id':f'synthetic-{i:03}', 'name':f'Synthetic {i:03}', 'kind':'star',
                'color':'#66bbff','model_id':'synthetic'} for i in range(2048)]
    selected = [row for row in objects if q.lower() in row['name'].lower() or q in row['id']]
    return {'version':'sources/1','revision':'synthetic-registry','objects':selected[:min(limit,128)],
            'total':2048,'models':[{'id':'synthetic','source':'SYNTHETIC HTTP TEST — no NASA data'}]}


@app.get('/api/search')
def search():
    return []


@app.get('/api/positions/v1/nearby')
async def nearby(at: str, anchor: str, dx: float, dy: float, dz: float, radius: float,
                 ox: float | None = None, oy: float | None = None, oz: float | None = None):
    result = metadata(at)
    if any(not math.isfinite(v) for v in [dx,dy,dz,radius]) or radius < 0:
        raise HTTPException(422,'Invalid synthetic area')
    await asyncio.sleep(state['delay']/1000)
    anchor_number = int(anchor.split('-')[1]) if anchor.startswith('synthetic-') else None
    center = [dx+(anchor_number//64*6000000+(anchor_number%64)*1000 if anchor_number is not None else 0),dy,dz]
    if any(v is not None for v in (ox,oy,oz)):
        if any(v is None or not math.isfinite(v) for v in (ox,oy,oz)):
            raise HTTPException(422,'Incomplete fixed origin')
        center = [ox+dx,oy+dy,oz+dz]
    result['sectors'] = []
    if anchor_number is not None:
        for number in range(32):
            delta = [max(number*6000000-center[0],0,center[0]-(number*6000000+63000)),
                     max(0,-center[1],center[1]-864),max(0,-center[2],center[2]-31500)]
            if math.hypot(*delta) <= radius:
                result['sectors'].append({'id':f'synthetic:{number}','revision':result['revision'],'object_count':64})
    return result


@app.get('/api/positions/v1/sectors/{sector}')
async def sector(sector: str, at: str, revision: str):
    if sector not in [f'synthetic:{i}' for i in range(32)]:
        raise HTTPException(404,'Unknown synthetic sector')
    metadata(at)
    await asyncio.sleep(12 if state['hang']==sector else (state['delay']+[200,0,150,50][int(sector.rsplit(':',1)[1])%4])/1000)
    if state['conflict']:
        state['conflict'] -= 1; state['revision'] += 1
        raise HTTPException(409,detail={'message':'Injected revision conflict'})
    if revision != current_revision():
        raise HTTPException(409,detail={'message':'Synthetic revision changed'})
    if state['fail'] == sector:
        raise HTTPException(422,detail={'message':'Injected permanent partial failure'})
    result = payload(at,sector)
    if state['mixed']==sector:
        result['jd_tdb'] += 1
    body = json.dumps(result,separators=(',',':'),allow_nan=False).encode()
    assert len(body) <= 256*1024
    return Response(body,media_type='application/json',headers={'Cache-Control':'no-store'})


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8000,log_level='warning')
