"""Versioned offline positions, separate from catalog snapshots and legacy v2."""

import hashlib
import json
import asyncio
import re
import sqlite3
from uuid import uuid4
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from backend.byte_cache import ByteLRU
from backend.position_work import PositionWork, PositionWorkCancelled
from data.ephemeris import Ephemeris, contract
from data.source_registry import REGISTRY


def install_position_api(app, etag_matches, registry=REGISTRY, engine_factory=None, work_limits=None,
                         temporal_index_factory=None):
    from data.temporal_index import ensure_real
    from backend.temporal_api import install_temporal_api
    temporal_index = None
    def get_index():
        nonlocal temporal_index
        if temporal_index is None:
            temporal_index = temporal_index_factory() if temporal_index_factory else ensure_real(registry=registry)
        return temporal_index

    cache = ByteLRU(1024 * 1024)
    lock = Lock()
    engine = None
    work = PositionWork(**(work_limits or {}))
    app.state.position_work = work

    @app.middleware('http')
    async def position_trace(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/positions/v1/'):
            for name in ('X-Astroverse-Client','X-Astroverse-Selection','X-Astroverse-Request'):
                value = request.headers.get(name,'')
                if re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',value):
                    response.headers[name] = value
            if 'X-Astroverse-Request' not in response.headers:
                response.headers['X-Astroverse-Request'] = uuid4().hex
        return response

    @asynccontextmanager
    async def lifespan(app):
        nonlocal engine
        try:
            yield
        finally:
            await asyncio.to_thread(work.close)
            with lock:
                if engine is not None:
                    engine.close()
                    engine = None

    router = APIRouter(prefix='/api/positions/v1', lifespan=lifespan)

    @app.get('/api/sources/v1/objects')
    def sources(request: Request, offset: int = Query(0, ge=0, le=1000000),
                limit: int = Query(128, ge=1, le=128), q: str = Query('', max_length=128),
                revision: str | None = Query(None, max_length=64)):
        try:
            with get_index().snapshot() as snapshot:
                if snapshot.metadata['profile'] == 'synthetic-affine':
                    current = snapshot.metadata['registry_revision']
                    if revision is not None and revision != current:
                        raise HTTPException(409, 'Registry changed; restart paging')
                    rows = snapshot.db.execute('SELECT id,n FROM bodies WHERE n>=? AND instr(id,?)>0 ORDER BY n LIMIT ?', (offset,q,limit+1)).fetchall()
                    result = {'version':'sources/1', 'revision':current, 'synthetic':True,
                              'objects':[{'id':row['id'], 'name':row['id'], 'kind':'star', 'color':'#66bbff', 'model_id':'synthetic-affine'} for row in rows[:limit]],
                              'models':[{'id':'synthetic-affine', 'source':'SYNTHETIC affine lattice; no measured astronomy'}],
                              'total':snapshot.metadata['count'], 'next_offset':rows[limit-1]['n']+1 if len(rows)>limit else None}
                    payload = json.dumps(result,separators=(',',':'),allow_nan=False).encode()
                    etag = '"'+hashlib.sha256(payload).hexdigest()+'"'
                    headers = {'ETag':etag,'Cache-Control':'public, max-age=0, must-revalidate'}
                    return Response(status_code=304,headers=headers) if etag_matches(request.headers.get('if-none-match'),etag) else Response(payload,media_type='application/json',headers=headers)
        except HTTPException:
            raise
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise HTTPException(503, 'Temporal publication unavailable', headers={'Cache-Control':'no-store'}) from exc
        if revision is not None and revision != registry.revision:
            raise HTTPException(409, 'Registry changed; restart paging')
        payload = json.dumps(registry.page(offset, limit, q), separators=(',', ':'), allow_nan=False).encode()
        if len(payload) > 256 * 1024:
            raise HTTPException(413, 'Registry page exceeds byte limit')
        etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
        headers = {'ETag': etag, 'Cache-Control': 'public, max-age=0, must-revalidate'}
        return Response(status_code=304, headers=headers) if etag_matches(request.headers.get('if-none-match'), etag) else Response(payload, media_type='application/json', headers=headers)

    @router.get('/contract')
    def get_contract(request: Request):
        try:
            with get_index().snapshot() as snapshot:
                model_contract = dict(snapshot.metadata['coordinates'])
                model_contract['temporal_revision'] = snapshot.metadata['temporal_revision']
                model_contract['temporal_selection'] = {'max_sectors':16,'max_members_per_sector':128,'max_candidate_members':2048,'max_response_bytes':262144}
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise HTTPException(503, 'Temporal publication unavailable', headers={'Cache-Control':'no-store'}) from exc
        payload = json.dumps(model_contract, separators=(',', ':'), allow_nan=False).encode()
        etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
        headers = {'ETag': etag, 'Cache-Control': 'public, max-age=0, must-revalidate'}
        if etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        return Response(payload, media_type='application/json', headers=headers)

    def compute(at, jd_tdb, ids, cancelled):
        nonlocal engine
        def check():
            if cancelled is not None and cancelled.is_set():
                raise PositionWorkCancelled()
        check()
        # Poll the engine lock so disconnected callers cannot wait indefinitely.
        while not lock.acquire(timeout=.025):
            check()
        try:
            check()
            try:
                if engine is None:
                    engine = engine_factory() if engine_factory else Ephemeris(registry=registry)
            except (OSError, ValueError) as exc:
                raise HTTPException(503, 'Verified ephemeris unavailable', headers={'Cache-Control': 'no-store'}) from exc
            check()
            # Parsing and interval validation precede validators, including *.
            try:
                key = (registry.revision, at, jd_tdb, tuple(ids) if ids is not None else None)
                payload = cache.get(key)
                if payload is None:
                    result = engine.evaluate(at=at, jd_tdb=jd_tdb, ids=ids)
                    check()
                    payload = json.dumps(result, separators=(',', ':'), allow_nan=False).encode()
                    if len(payload) > 256 * 1024:
                        raise HTTPException(413, 'Position response exceeds byte limit')
                    check()
                    cache.put(key, payload)
            except (ValueError, OverflowError) as exc:
                raise HTTPException(422, detail={'code': 'unsupported_simulation_time', 'message': str(exc)}) from exc
        finally:
            lock.release()
        check()
        return json.loads(payload)

    install_temporal_api(router, etag_matches, work, get_index, compute)

    app.include_router(router)
