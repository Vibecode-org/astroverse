"""Legacy catalog representations backed by one pinned SQLite snapshot.

Owns response serialization, filtered-response budgets and streaming lifetime.
Application policy and mutable dependencies are supplied by the caller.
"""

import hashlib
import json

from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from data.catalog import encode_binary_catalog, encode_binary_catalog_v2


def disk_objects(request, q, kind, scale, version, *, catalog, cache, etag_matches,
                 cache_control, max_objects, max_bytes):
    # Keep the transaction alive until the streaming response is consumed.
    context = catalog.snapshot()
    index = context.__enter__()
    try:
        revision = index.metadata["catalog_revision"]
        key = ("legacy", revision, version, q, kind, scale)
        etag = '"' + hashlib.sha256(repr(key).encode()).hexdigest() + '"'
        headers = {"ETag": etag, "Cache-Control": cache_control, "Vary": "Accept"}
        if not any((q, kind, scale)) and etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        if version != "json" and not any((q, kind, scale)):
            headers.update({"X-Object-Count": str(index.metadata["object_count"]),
                            "X-Catalog-Format": version,
                            "Content-Length": str(index.binary_size(version))})
            def stream_binary():
                try:
                    yield from index.binary(version)
                finally:
                    stream_context.__exit__(None, None, None)
            stream_context = context
            response = StreamingResponse(stream_binary(), media_type="application/octet-stream", headers=headers,
                                         background=BackgroundTask(stream_context.__exit__, None, None, None))
            context = None
            return response
        if version == "json" and not any((q, kind, scale)):
            def stream_json():
                try:
                    yield b"["
                    separator = b""
                    buffer = bytearray()
                    for payload in index.select(raw=True):
                        buffer.extend(separator + payload.encode())
                        if len(buffer) >= 65536:
                            yield bytes(buffer)
                            buffer.clear()
                        separator = b","
                    yield bytes(buffer) + b"]"
                finally:
                    stream_context.__exit__(None, None, None)
            stream_context = context
            response = StreamingResponse(stream_json(), media_type="application/json", headers=headers,
                                         background=BackgroundTask(stream_context.__exit__, None, None, None))
            context = None
            return response
        payload = cache.get(key)
        if payload is None:
            rows, row_bytes = [], 0
            for raw in index.select(q=q, kind=kind, scale=scale, limit=max_objects + 1, raw=True):
                row_bytes += len(raw.encode())
                if len(rows) >= max_objects or row_bytes > max_bytes:
                    raise HTTPException(413, "Legacy filtered response exceeds budget; use /api/spatial/v1")
                rows.append(json.loads(raw))
            if version == "json":
                payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
            else:
                encoder = encode_binary_catalog_v2 if version == "v2" else encode_binary_catalog
                payload = encoder(rows)
            if len(payload) > max_bytes:
                raise HTTPException(413, "Legacy filtered response exceeds byte budget")
            cache.put(key, payload)
            count = len(rows)
        else:
            count = (int.from_bytes(payload[8:12], "little") if version != "json" else 0)
        # A conditional cannot bypass filtered object/byte budget validation.
        if etag_matches(request.headers.get("if-none-match"), etag):
            return Response(status_code=304, headers=headers)
        if version != "json":
            headers.update({"X-Object-Count": str(count), "X-Catalog-Format": version})
        return Response(payload, media_type="application/json" if version == "json" else "application/octet-stream", headers=headers)
    finally:
        if context is not None:
            context.__exit__(None, None, None)

