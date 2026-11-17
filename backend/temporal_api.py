"""Bounded requested-time selection using the shared position admission pool."""
import hashlib
import json
import math
import sqlite3
import time as clock

from fastapi import HTTPException, Query, Request
from fastapi.responses import Response
from data.physical_hierarchy import attach_hierarchy
from data.temporal_index import MAX_BYTES, MAX_MEMBERS, MAX_SECTORS, normalize_time


def install_temporal_api(router, etag_matches, work, get_index, compute):
    def reply(request, result):
        payload = json.dumps(result, separators=(',', ':'), allow_nan=False).encode()
        if len(payload) > MAX_BYTES:
            raise HTTPException(413, 'Temporal position response byte budget exceeded')
        etag = '"' + hashlib.sha256(payload).hexdigest() + '"'
        duration = (clock.perf_counter()-request.state.temporal_started)*1000
        metric = 'temporal' if request.url.path.endswith('/nearby') else 'positions'
        headers = {'Server-Timing': f'{metric};dur={duration:.3f}', 'ETag': etag, 'Cache-Control': 'public, max-age=0, must-revalidate',
                   'X-Coordinate-Contract': 'positions/1'}
        if etag_matches(request.headers.get('if-none-match'), etag):
            return Response(status_code=304, headers=headers)
        return Response(payload, media_type='application/json', headers=headers)

    def check(snapshot, revision, temporal_revision, cancelled):
        from backend.position_work import PositionWorkCancelled
        if cancelled.is_set():
            raise PositionWorkCancelled()
        metadata = snapshot.metadata
        if ((revision is not None and revision != metadata['revision']) or
                (temporal_revision is not None and temporal_revision != metadata['temporal_revision'])):
            raise HTTPException(409, detail={'code': 'position_revision_changed',
                                           'message': 'Position publication changed; rediscover sectors'},
                                headers={'Cache-Control': 'no-store'})

    def check_time(snapshot, jd):
        lower, upper = snapshot.metadata['interval']
        if not lower <= jd < upper:
            raise HTTPException(422, detail={'code':'unsupported_simulation_time', 'message':'Outside temporal publication interval'})

    def frame(snapshot, rows, at, jd_tdb, jd, evaluated_at, sector, cancelled):
        metadata = snapshot.metadata
        if metadata['profile'] == 'real-five':
            result = compute(at, jd_tdb, [row['id'] for row in rows], cancelled)
            if result['revision'] != metadata['revision'] or result['registry_revision'] != metadata['registry_revision']:
                raise ValueError('temporal publication and verified solver revisions differ')
        else:
            result = attach_hierarchy({'version': 'positions/1', 'revision': metadata['revision'],
                    'registry_revision': metadata['registry_revision'], 'coordinates': metadata['coordinates'],
                    'evaluated_at': evaluated_at, 'jd_tdb': jd, 'input_time_scale': 'UTC' if at is not None else 'TDB',
                    'sector': sector, 'objects': snapshot.positions(rows, jd), 'synthetic': True})
        result['temporal_revision'] = metadata['temporal_revision']
        return result

    def guarded(operation):
        try:
            return operation()
        except HTTPException:
            raise
        except OverflowError as exc:
            raise HTTPException(413, str(exc), headers={'Cache-Control': 'no-store'}) from exc
        except (sqlite3.Error, OSError, KeyError, TypeError) as exc:
            raise HTTPException(503, 'Temporal publication unavailable', headers={'Cache-Control': 'no-store'}) from exc
        except ValueError as exc:
            # Time parsing is handled separately; invalid publications fail closed.
            raise HTTPException(503, 'Temporal publication invalid', headers={'Cache-Control': 'no-store'}) from exc

    def time(at, jd_tdb):
        try:
            return normalize_time(at, jd_tdb)
        except (ValueError, OverflowError) as exc:
            raise HTTPException(422, detail={'code': 'unsupported_simulation_time', 'message': str(exc)}) from exc

    @router.get('/nearby')
    async def nearby(request: Request, anchor: str, dx: float, dy: float, dz: float, radius: float,
                     at: str | None = Query(None, max_length=64), jd_tdb: float | None = None,
                     revision: str | None = Query(None, max_length=256),
                     temporal_revision: str | None = Query(None, max_length=256),
                     ox: float | None = None, oy: float | None = None, oz: float | None = None):
        if len(anchor) > 512 or any(not math.isfinite(v) or abs(v) > 1e13 for v in (dx, dy, dz, radius)) or radius < 0:
            raise HTTPException(422, 'Invalid physical neighborhood')
        fixed = None if all(v is None for v in (ox, oy, oz)) else [ox, oy, oz]
        if fixed is not None and any(v is None or not math.isfinite(v) or abs(v) > 1e13 for v in fixed):
            raise HTTPException(422, 'Expected complete finite ICRF/SSB origin km within 1e13')
        def operation(cancelled):
            request.state.temporal_started = clock.perf_counter()
            jd, evaluated_at = time(at, jd_tdb)
            def build():
                with get_index().snapshot() as snapshot:
                    check_time(snapshot, jd)
                    check(snapshot, revision, temporal_revision, cancelled)
                    anchor_row = snapshot.object(anchor)
                    if anchor_row is None:
                        raise HTTPException(422, 'Unsupported physical anchor')
                    if fixed is not None:
                        origin = fixed
                    else:
                        anchor_frame = frame(snapshot, [anchor_row], at, jd_tdb, jd, evaluated_at, 'anchor', cancelled)
                        origin = anchor_frame['objects'][0]['position']
                        if origin is None:
                            raise HTTPException(422, 'Anchor position unknown')
                    center = [value + delta for value, delta in zip(origin, (dx, dy, dz))]
                    sectors = snapshot.candidates(center, radius, jd)
                    # The real index intentionally admits all five centers. Only
                    # their exact current-time AABB is used for spatial rejection.
                    if snapshot.metadata['profile'] == 'real-five':
                        rows = snapshot.members('solar:verified')
                        result = frame(snapshot, rows, at, jd_tdb, jd, evaluated_at, 'solar:verified', cancelled)
                        vectors = [row['position'] for row in result['objects'] if row['position'] is not None]
                        lower = [min(v[a] for v in vectors) for a in range(3)]
                        upper = [max(v[a] for v in vectors) for a in range(3)]
                        delta = [max(lower[a]-center[a], 0, center[a]-upper[a]) for a in range(3)]
                        sectors = ([{'id': 'solar:verified', 'object_count': len(rows), 'min': lower, 'max': upper}]
                                   if math.hypot(*delta) <= radius else [])
                        result['objects'] = []
                        result.pop('hierarchy', None)
                    else:
                        metadata = snapshot.metadata
                        result = {'version': 'positions/1', 'revision': metadata['revision'],
                                  'temporal_revision': metadata['temporal_revision'], 'registry_revision': metadata['registry_revision'],
                                  'coordinates': metadata['coordinates'], 'evaluated_at': evaluated_at,
                                  'jd_tdb': jd, 'input_time_scale': 'UTC' if at is not None else 'TDB', 'objects': [], 'synthetic': True}
                    for sector in sectors:
                        sector['revision'] = snapshot.metadata['revision']
                    result.update(sectors=sectors,
                                  query={'anchor': anchor, 'offset_km': [dx, dy, dz], 'radius_km': radius},
                                  selection={'method': 'unconditional-five-exact-aabb' if snapshot.metadata['profile'] == 'real-five' else 'conservative-affine-swept-aabb',
                                             'false_positives_possible': True, 'max_sectors': MAX_SECTORS,
                                             'max_members_per_sector': MAX_MEMBERS, 'max_candidate_members': MAX_SECTORS*MAX_MEMBERS})
                    if fixed is not None:
                        result['query']['origin_km'] = fixed
                    check_time(snapshot, jd)
                    check(snapshot, revision, temporal_revision, cancelled)
                    return reply(request, result)
            return guarded(build)
        return await work.run(request, operation)

    @router.get('/sectors/{sector_id}')
    async def sector(request: Request, sector_id: str,
                     at: str | None = Query(None, max_length=64), jd_tdb: float | None = None,
                     revision: str | None = Query(None, max_length=256),
                     temporal_revision: str | None = Query(None, max_length=256)):
        if len(sector_id) > 256:
            raise HTTPException(422, 'Sector ID too long')
        def operation(cancelled):
            request.state.temporal_started = clock.perf_counter()
            jd, evaluated_at = time(at, jd_tdb)
            def build():
                with get_index().snapshot() as snapshot:
                    check_time(snapshot, jd)
                    check(snapshot, revision, temporal_revision, cancelled)
                    rows = snapshot.members(sector_id)
                    if rows is None:
                        raise HTTPException(404, 'Unknown physical sector')
                    result = frame(snapshot, rows, at, jd_tdb, jd, evaluated_at, sector_id, cancelled)
                    check_time(snapshot, jd)
                    check(snapshot, revision, temporal_revision, cancelled)
                    return reply(request, result)
            return guarded(build)
        return await work.run(request, operation)

    @router.get('/objects/{object_id}')
    async def object_position(request: Request, object_id: str,
                              at: str | None = Query(None, max_length=64), jd_tdb: float | None = None,
                              revision: str | None = Query(None, max_length=256),
                              temporal_revision: str | None = Query(None, max_length=256)):
        if len(object_id) > 512:
            raise HTTPException(422, 'Object ID too long')
        def operation(cancelled):
            request.state.temporal_started = clock.perf_counter()
            jd, evaluated_at = time(at, jd_tdb)
            def build():
                with get_index().snapshot() as snapshot:
                    check_time(snapshot, jd)
                    check(snapshot, revision, temporal_revision, cancelled)
                    row = snapshot.object(object_id)
                    if row is None and snapshot.metadata['profile'] == 'real-five':
                        result = compute(at, jd_tdb, [object_id], cancelled)
                        result['temporal_revision'] = snapshot.metadata['temporal_revision']
                    elif row is None:
                        result = frame(snapshot, [], at, jd_tdb, jd, evaluated_at, 'unknown', cancelled)
                        result['objects'] = [{'id': object_id, 'status': 'unknown', 'position': None, 'reason': 'no_synthetic_model'}]
                        result = attach_hierarchy(result)
                    else:
                        result = frame(snapshot, [row], at, jd_tdb, jd, evaluated_at, row['sector_id'], cancelled)
                    return reply(request, result)
            return guarded(build)
        return await work.run(request, operation)
