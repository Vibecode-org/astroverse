"""Versioned offline positions, separate from catalog snapshots and legacy v2."""

import hashlib
import json
import math
import asyncio
import re
from uuid import uuid4
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from backend.byte_cache import ByteLRU
from backend.position_work import PositionWork, PositionWorkCancelled
from data.ephemeris import Ephemeris, contract
from data.source_registry import REGISTRY


def install_position_api(app, etag_matches, registry=REGISTRY, engine_factory=None, work_limits=None):
    targets = registry.targets
    cache = ByteLRU(1024 * 1024)
    lock = Lock()
    engine = None
    work = PositionWork(**(work_limits or {}))

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
        payload = json.dumps(contract(registry), separators=(',', ':'), allow_nan=False).encode()
        etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
        headers = {'ETag': etag, 'Cache-Control': 'public, max-age=0, must-revalidate'}
        if etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        return Response(payload, media_type='application/json', headers=headers)

    def evaluate(request, at, jd_tdb, ids, neighborhood=None, expected_revision=None, cancelled=None):
        nonlocal engine
        def check():
            if cancelled is not None and cancelled.is_set():
                raise PositionWorkCancelled()
        check()
        if expected_revision is not None and expected_revision != contract(registry)['revision']:
            raise HTTPException(409, detail={'code': 'position_revision_changed',
                                           'message': 'Position revision changed; rediscover sectors'},
                                headers={'Cache-Control': 'no-store'})
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
                if ids is None and len(targets) > 128:
                    raise HTTPException(413, 'Physical sector exceeds 128 centers; use individual reads')
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
        if neighborhood is not None:
            anchor, dx, dy, dz, radius, fixed_origin = neighborhood
            result = json.loads(payload)
            vectors = {row['id']: row['position'] for row in result['objects']}
            origin = vectors[anchor] if fixed_origin is None else fixed_origin
            center = [origin[axis] + delta for axis, delta in enumerate((dx, dy, dz))]
            lower = [min(v[axis] for v in vectors.values()) for axis in range(3)]
            upper = [max(v[axis] for v in vectors.values()) for axis in range(3)]
            delta = [max(lower[a]-center[a], 0, center[a]-upper[a]) for a in range(3)]
            result['objects'] = []
            result.pop('hierarchy', None)  # manifest only; it carries no body placements
            result['sectors'] = ([{'id': 'solar:verified', 'revision': result['revision'],
                                   'min': lower, 'max': upper, 'object_count': len(vectors)}]
                                 if math.hypot(*delta) <= radius else [])
            result['query'] = {'anchor': anchor, 'offset_km': [dx,dy,dz], 'radius_km': radius}
            if fixed_origin is not None:
                result['query']['origin_km'] = fixed_origin
            payload = json.dumps(result, separators=(',', ':'), allow_nan=False).encode()
        etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
        headers = {'ETag': etag, 'Cache-Control': 'public, max-age=0, must-revalidate',
                   'X-Coordinate-Contract': 'positions/1'}
        if etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        return Response(payload, media_type='application/json', headers=headers)

    @router.get('/sectors/solar:verified')
    async def solar(request: Request, at: str | None = Query(None, max_length=64), jd_tdb: float | None = None,
              revision: str | None = Query(None, max_length=256)):
        return await work.run(request, lambda cancelled: evaluate(request, at, jd_tdb, None, expected_revision=revision, cancelled=cancelled))

    @router.get('/nearby')
    async def nearby(request: Request, anchor: str, dx: float, dy: float, dz: float,
               radius: float, at: str | None = Query(None, max_length=64), jd_tdb: float | None = None,
               revision: str | None = Query(None, max_length=256),
               ox: float | None = None, oy: float | None = None, oz: float | None = None):
        # The camera offset is ICRF km relative to a confirmed moving anchor.
        # Re-evaluating both anchor and bounds prevents static-root omissions.
        if (anchor not in targets or any(not math.isfinite(v) or abs(v)>1e13 for v in (dx,dy,dz,radius))
                or radius < 0):
            raise HTTPException(422, 'Invalid physical neighborhood; expected supported anchor and finite km within 1e13')
        fixed_origin = None if all(v is None for v in (ox,oy,oz)) else [ox,oy,oz]
        if fixed_origin is not None and any(v is None or not math.isfinite(v) or abs(v)>1e13 for v in fixed_origin):
            raise HTTPException(422, 'Expected complete finite ICRF/SSB origin km within 1e13')
        return await work.run(request, lambda cancelled: evaluate(request, at, jd_tdb, None, (anchor, dx, dy, dz, radius, fixed_origin), expected_revision=revision, cancelled=cancelled))

    @router.get('/objects/{object_id}')
    async def object_position(request: Request, object_id: str,
                        at: str | None = Query(None, max_length=64), jd_tdb: float | None = None,
                        revision: str | None = Query(None, max_length=256)):
        if len(object_id) > 512:
            raise HTTPException(422, 'Object ID too long')
        return await work.run(request, lambda cancelled: evaluate(request, at, jd_tdb, [object_id], expected_revision=revision, cancelled=cancelled))

    app.include_router(router)
