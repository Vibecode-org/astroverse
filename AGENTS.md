# Astroverse

Browser 3D planetarium (React + Three.js frontend, FastAPI backend), runs via Docker. Catalog built at container startup.

## Commands

- Start: `docker compose up --build -d`, open http://localhost:5173
- Stop: `docker compose down`
- Logs: `docker compose logs -f backend` / `frontend`

Backend tests (run inside container; `-w /app` is required because image WORKDIR is `/app/backend` but tests live in `/app/tests`):

```bash
docker compose build backend
docker compose run --rm --no-deps -w /app backend python -m unittest discover -s tests -t . -v
```

Browser smoke (pytest + Playwright; needs frontend+API running with 3471-object catalog):

```bash
python3 -m venv /tmp/astroverse-smoke-env
/tmp/astroverse-smoke-env/bin/python -m pip install playwright pytest
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -v
```

100k stress smoke (needs the 100k stack; the module is marked `stack100k` and is skipped automatically on the 3471 stack):

```bash
python3 data/gen_catalog_100k.py
docker compose -f docker-compose.yml -f docker-compose.100k.yml up --build -d
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -m stack100k -v
```

Smoke tests use system Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`; no `playwright install` needed. Headless uses SwiftShader; use `SMOKE_HEADED=1` for a visible window. Run one module/test with `.../pytest tests/browser_smoke/smoke_time.py::TestTime::test_... -v`.

Both stacks serve port 5173, so modules are marked `stack3471` / `stack100k` and `conftest.py` skips the ones that do not match `/api/health` (reason names the served catalog size). There is no `SMOKE_STRESS` env var any more.

Frontend dev: `cd frontend && npm run dev` (Vite, port 5173, proxies `/api` to 127.0.0.1:8000). Build: `npm run build`.

## Architecture

- `backend/app.py` — FastAPI app (`/api/health`, `/api/objects` JSON/v1/v2 with ETag, `/api/search`, `/api/objects/{id}`, `/api/live-ephemeris`)
- `backend/entrypoint.py` — prepares catalog before uvicorn starts; mode from `ASTROVERSE_CATALOG_MODE` (`offline`/`online`/`existing`)
- `data/` — catalog sources/builders (`sources.py`, `build_catalog.py`, `catalog.py`, `catalog_seed.json`); `data/objects.json` is generated (gitignored)
- `frontend/src/` — React + Three.js
- `tests/test_*.py` — unittest backend tests; `tests/browser_smoke/smoke_*.py` — pytest Playwright smoke (named `smoke_*` so unittest discover skips them)

## Gotchas

- `tests/test_api.py` sets `ASTROVERSE_CATALOG_PATH` to `data/catalog_seed.json` so it doesn't depend on generated `data/objects.json`.
- Smoke tests require exactly 3471 objects in the catalog (the `stack3471` modules); `smoke_stress` needs 100000 and is skipped otherwise.
- `pytest.ini` registers the two markers; a marker name not registered there fails collection with a warning-as-error setup.
- Backend port 8000 is not published; frontend nginx proxies `/api` in Docker.
- Smoke test probe uses React fiber internals (`window.__astroverseSmoke`); may need updates after React upgrades.
- One-off container commands (tests, shells) must not be first arg `uvicorn` or entrypoint rebuilds catalog.
- The 100k stack and normal stack cannot run simultaneously on port 5173: switch back with `docker compose up --build -d` (without the 100k override). Check `/api/health` — should be `3471` for normal smoke, `100000` for stress.
- v2 binary endpoint: `GET /api/objects?format=v2` returns `application/octet-stream` with header `X-Catalog-Format: v2`. v1 JSON remains the default.
- nginx gzips `application/octet-stream` (v1 and v2 binary): 13 MB on 100k → ~2.46 MB on the wire. Gzipped responses are chunked and have no `Content-Length`, so tests assert `Content-Encoding` plus the decoded body (`response.body()`) instead of the header.
- `/api/objects` responses carry `ETag` + `Cache-Control: public, max-age=0, must-revalidate` + `Vary: Accept`. nginx rewrites the ETag of gzip responses to a weak `W/"…"` validator, so anything comparing validators must strip `W/` (see `etag_matches`). The ETag includes the percent-encoded `q`: header values are latin-1 and a Cyrillic query would otherwise raise.
- `backend/app.py` keeps a lazy catalog index (`catalog_index()`): `id → object` plus one lowercase haystack per object. It rebuilds only when the `CATALOG` list object is replaced, so tests that swap the catalog get a fresh index instead of stale results.
- `frontend/src/scene/buildSolarSystem.js::scaleCatalog` caches the derived rows in a `WeakMap` keyed by the catalog array, including the scale mode. Do not mutate those rows: they are shared by every mount of the scene.
- Headless SwiftShader renders the 100k catalog at ~0.5 fps (~2.5 s per frame). `smoke_stress` raises action timeouts to 60 s and clicks rows through `element.click()` because Playwright's real mouse click waits for a frame ack.