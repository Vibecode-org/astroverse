"""Bounded, versioned snapshot API. Legacy render v2 is never physical data."""

import hashlib
import json
import math
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from backend.byte_cache import ByteLRU
from data.coordinates import coordinate_contract, snapshot_coordinates
from data.sectors import ResultLimitExceeded
from data.runtime_catalog import CatalogUnavailable

MAX_SECTORS = 128
MAX_OBJECTS = 512
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_RADIUS_LY = 1_000_000
MAX_CENTER_LY = 1e12


def reject_time(at):
    if at is not None:
        raise HTTPException(422, detail={"code": "unsupported_simulation_time",
                            "message": "Only catalog_snapshot is supported; no epoch or root-motion model is available"})


def install_sector_api(app, catalog, etag_matches, cache_bytes):
    router = APIRouter(prefix="/api/spatial/v1")
    cache = ByteLRU(cache_bytes)
    app.state.sector_cache = cache

    @app.exception_handler(CatalogUnavailable)
    async def unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Catalog snapshot unavailable"},
                            headers={"Retry-After": "1", "Cache-Control": "no-store"})

    def reply(request, key, build, snapshot=None):
        etag = '"' + hashlib.sha256(repr(key).encode()).hexdigest() + '"'
        headers = {"ETag": etag, "Cache-Control": "public, max-age=0, must-revalidate",
                   "X-Coordinate-Contract": "coordinates/1"}
        if snapshot is not None:
            headers["X-Catalog-Snapshot"] = snapshot
        payload = cache.get(key)
        if payload is None:
            payload = json.dumps(build(), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
            if len(payload) > MAX_RESPONSE_BYTES:
                raise HTTPException(413, "Response byte budget exceeded; reduce limit")
            cache.put(key, payload)
        # Validate an uncached representation before evaluating conditions:
        # If-None-Match must not turn a normal 413 into a successful 304.
        if etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        return Response(payload, media_type="application/json", headers=headers)

    @router.get("/contract")
    def contract():
        return coordinate_contract()

    @router.get("/nearby")
    def nearby(request: Request, scale: Literal["local", "galaxy"],
               frame: Literal["equatorial", "galactic"],
               x: float, y: float, z: float,
               radius: float = Query(32, ge=0, le=MAX_RADIUS_LY),
               limit: int = Query(MAX_SECTORS, ge=1, le=MAX_SECTORS),
               at: str | None = None, snapshot: str | None = None):
        reject_time(at)
        if any(not math.isfinite(v) or abs(v) > MAX_CENTER_LY for v in (x, y, z)) or not math.isfinite(radius):
            raise HTTPException(422, "Coordinates must be finite and within the supported query range")
        with catalog.snapshot() as index:
            revision = index.metadata["catalog_revision"]
            check_snapshot(snapshot, revision)
            def build():
                try:
                    sectors = index.nearby(scale, frame, (x, y, z), radius, limit=limit)
                except ResultLimitExceeded as exc:
                    raise HTTPException(413, str(exc)) from exc
                return {"version": "spatial/1", "snapshot": revision,
                        "coordinates": coordinate_contract(), "sectors": sectors}
            return reply(request, ("nearby/1", revision, scale, frame, x, y, z, radius, limit), build)

    @router.get("/objects/{object_id}/sector")
    def locate(request: Request, object_id: str, at: str | None = None,
               snapshot: str | None = None):
        reject_time(at)
        with catalog.snapshot() as index:
            revision = index.metadata["catalog_revision"]
            check_snapshot(snapshot, revision)
            sid = index.locate(object_id)
            if sid is None:
                raise HTTPException(404, "Object not found")
            return reply(request, ("locate/1", revision, object_id), lambda: {
                "version": "spatial/1", "snapshot": revision, "object_id": object_id,
                "sector": index.sector(sid),
                "coordinates": snapshot_coordinates(index.object(object_id)),
                "membership": "root_catalog_snapshot; not the body's physical position"})

    @router.get("/sectors/{sector_id:path}")
    def sector(request: Request, sector_id: str,
               limit: int = Query(MAX_OBJECTS, ge=1, le=MAX_OBJECTS),
               after: str | None = Query(None, max_length=512),
               at: str | None = None, snapshot: str | None = None):
        reject_time(at)
        with catalog.snapshot() as index:
            revision = index.metadata["catalog_revision"]
            check_snapshot(snapshot, revision)
            info = index.sector(sector_id)
            if info is None:
                raise HTTPException(404, "Sector not found")
            def build():
                try:
                    rows = list(index.select(sector=sector_id, after=after, limit=limit,
                                             max_bytes=MAX_RESPONSE_BYTES))
                except ResultLimitExceeded as exc:
                    raise HTTPException(413, str(exc)) from exc
                more = bool(rows) and index.has_more(sector_id, rows[-1]["id"])
                return {"version": "spatial/1", "sector": info,
                        "coordinates": coordinate_contract(),
                        "objects": [{"object": row, "coordinates": snapshot_coordinates(row)} for row in rows],
                        "next_after": rows[-1]["id"] if more else None}
            # Sector validators survive unrelated catalog edits. Clients pin a
            # catalog snapshot via the query parameter, checked before any 304.
            return reply(request, ("sector/1", sector_id, info["revision"], limit, after), build,
                         snapshot=revision)

    app.include_router(router)


def check_snapshot(expected, current):
    if expected is not None and expected != current:
        raise HTTPException(409, detail={"code": "snapshot_changed", "snapshot": current})
