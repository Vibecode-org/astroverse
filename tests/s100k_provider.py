"""Opt-in SQLite-backed synthetic physical workload. Never imported by production."""
import math
import os
import sqlite3
from pathlib import Path
from fastapi import HTTPException
# Give the old fixture its own module globals: importing this opt-in app must
# not mutate the ordinary 32-sector fixture used by other regression tests.
import importlib.util
import sys
_spec = importlib.util.spec_from_file_location('tests._s100k_base', Path(__file__).with_name('sector_provider.py'))
base = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = base
_spec.loader.exec_module(base)

COUNT = 100000
SIZE = 1000
DB = Path(os.environ.get('ASTROVERSE_SYNTHETIC_DB', '/tmp/astroverse-s100k.sqlite'))

def build(path=DB):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS bodies (n INTEGER PRIMARY KEY, id TEXT UNIQUE, x REAL, y REAL, z REAL)')
        if db.execute('SELECT count(*) FROM bodies').fetchone()[0] != COUNT:
            db.execute('DELETE FROM bodies')
            def rows():
                for n in range(COUNT):
                    k = 50000 if n == 50001 else n
                    yield n, f'synthetic-{n:05}', (k % 400 - 199.5)*4000, 0, (k // 400 - 124.5)*4000
            db.executemany('INSERT INTO bodies VALUES (?,?,?,?,?)', rows())
        db.execute('CREATE INDEX IF NOT EXISTS sector ON bodies(n)')

build()
original_metadata = base.metadata

def metadata(at):
    result = original_metadata(at)
    result.update(synthetic=True, profile='synthetic-s100k')
    return result
base.metadata = metadata
base.current_revision = lambda: f'synthetic-s100k-{base.state["revision"]}'
base.state['delay'] = 0

def payload(at, sector):
    result = metadata(at)
    number = int(sector.split(':')[-1])
    with sqlite3.connect(DB) as db:
        rows = db.execute('SELECT id,x,y,z FROM bodies WHERE n>=? AND n<? ORDER BY n', (number*SIZE,(number+1)*SIZE)).fetchall()
    result.update(sector=sector, objects=[{'id':id, 'status':'computed', 'source':'synthetic stationary lattice', 'position':[x,y,z]} for id,x,y,z in rows])
    return result
base.payload = payload
# Replace fixture handlers while retaining its transport fault controls/metrics.
base.app.router.routes[:] = [r for r in base.app.router.routes if getattr(r,'path','') not in ('/api/health','/api/sources/v1/objects','/api/positions/v1/nearby','/api/positions/v1/sectors/{sector}')]
app = base.app

@app.get('/api/health')
def health():
    return {'status':'ok','objects':COUNT,'synthetic':True,'profile':'synthetic-s100k'}

@app.get('/api/sources/v1/objects')
def sources(limit:int=128,q:str=''):
    with sqlite3.connect(DB) as db:
        if q:
            rows = db.execute('SELECT id FROM bodies WHERE instr(id,?)>0 ORDER BY n LIMIT ?', (q,min(max(limit,0),128))).fetchall()
        else:
            rows = db.execute('SELECT id FROM bodies ORDER BY n LIMIT ?', (min(max(limit,0),128),)).fetchall()
    return {'version':'sources/1','revision':'synthetic-registry','profile':'synthetic-s100k', 'objects':[{'id':r[0],'name':r[0],'kind':'star','color':'#66bbff','model_id':'synthetic'} for r in rows], 'total':COUNT,'models':[{'id':'synthetic','source':'SYNTHETIC S-100k — stationary artificial centers, not observations'}]}

@app.get('/api/positions/v1/nearby')
async def nearby(at:str,anchor:str,dx:float,dy:float,dz:float,radius:float,ox:float|None=None,oy:float|None=None,oz:float|None=None):
    result = metadata(at)
    if not all(math.isfinite(v) for v in (dx,dy,dz,radius)) or radius<0:
        raise HTTPException(422,'Invalid area')
    origin = [0,0,0]
    if any(v is not None for v in (ox,oy,oz)):
        if any(v is None or not math.isfinite(v) for v in (ox,oy,oz)):
            raise HTTPException(422,'Incomplete origin')
        origin = [ox,oy,oz]
    elif anchor.startswith('synthetic-'):
        with sqlite3.connect(DB) as db:
            row = db.execute('SELECT x,y,z FROM bodies WHERE id=?',(anchor,)).fetchone()
        if row: origin=list(row)
    center = [v+d for v,d in zip(origin,(dx,dy,dz))]
    # SQL bounds, followed by sphere/AABB intersection: camera-driven selection.
    with sqlite3.connect(DB) as db:
        bounds=db.execute('SELECT n/?,min(x),max(x),min(y),max(y),min(z),max(z),count(*) FROM bodies GROUP BY n/?',(SIZE,SIZE)).fetchall()
    result['sectors']=[]
    for n,x0,x1,y0,y1,z0,z1,count in bounds:
        delta=[max(lo-c,0,c-hi) for lo,hi,c in zip((x0,y0,z0),(x1,y1,z1),center)]
        if math.hypot(*delta)<=radius:
            result['sectors'].append({'id':f's100k:{n}','revision':result['revision'],'object_count':count})
    return result

@app.get('/api/positions/v1/sectors/{sector}')
async def sector(sector:str,at:str,revision:str):
    import asyncio
    if sector not in {f's100k:{i}' for i in range(100)}: raise HTTPException(404,'Unknown sector')
    await asyncio.sleep(12 if base.state['hang']==sector else base.state['delay']/1000)
    if base.state['conflict']:
        base.state['conflict']-=1; base.state['revision']+=1
        raise HTTPException(409,'Injected revision conflict')
    if revision != base.current_revision(): raise HTTPException(409,'Revision changed')
    if base.state['fail']==sector: raise HTTPException(422,'Injected failure')
    result=payload(at,sector)
    if base.state['mixed']==sector: result['jd_tdb']+=1
    return result

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8000,log_level='warning')
