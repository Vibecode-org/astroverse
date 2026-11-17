"""Explicit test-only synthetic app using production temporal routes/admission."""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from backend.position_api import install_position_api
from data.temporal_index import TemporalIndex

PATH = Path(os.environ.get('ASTROVERSE_TEMPORAL_DB', '/reports/temporal.sqlite'))
app = FastAPI(title='SYNTHETIC temporal streaming acceptance')

def etag_matches(value, etag):
    return bool(value) and (value.strip() == '*' or any(part.strip().removeprefix('W/') == etag for part in value.split(',')))

install_position_api(app, etag_matches, temporal_index_factory=lambda: TemporalIndex(PATH))

@app.get('/api/health')
def health():
    with TemporalIndex(PATH).snapshot() as snapshot:
        return {'status':'ok','objects':snapshot.metadata['count'],'synthetic':True,'profile':'synthetic-temporal'}

@app.get('/api/_test/metrics')
def metrics():
    return app.state.position_work.inspect()

@app.get('/api/_test/temporal')
def harness():
    return HTMLResponse('<!doctype html><meta charset="utf-8"><title>SYNTHETIC temporal acceptance</title><body style="margin:0;background:#000;color:#fff"><div style="position:absolute;z-index:2">SYNTHETIC affine temporal fixture — no measured astronomy</div><script src="/api/_test/harness.js"></script>')

@app.get('/api/_test/harness.js')
def javascript():
    path = Path(os.environ.get('ASTROVERSE_TEMPORAL_HARNESS', '/reports/temporal-harness.js'))
    if not path.is_file():
        raise HTTPException(404,'Temporal harness has not been built')
    return Response(path.read_bytes(),media_type='text/javascript')
