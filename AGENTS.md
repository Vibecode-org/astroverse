# Astroverse

React + Three.js / FastAPI, Docker. Runtime opens persistent SQLite; clean installs
copy the pinned bootstrap. Read this file and relevant docs, not the whole tree:
status/sequence `ROADMAP.md`, verification `docs/TEST_COVERAGE.md`, commands and
browser/benchmark details `tests/README.md`.

Goal: all known bodies as of each refresh, with source coverage/gaps recorded.
Million-row and S-100k milestones are neither catalog caps nor complete coverage.
Unknown physics stays null. All production body/model data must live/update in
DB; fixed JSON must not be the primary catalog. Build/startup require no full
catalog JSON. JSON remains valid for API, fixtures and tools; seed is test/tooling.
Check consumers before removing fixtures, configs or lockfiles.

## Team workflow

The primary agent leads: split scope, assign files, agree shared contracts,
integrate and verify. The user explicitly requires delegation for substantive
work; small isolated edits may be handled directly.

- `physicist`: physical semantics, JPL Horizons, ephemerides, coordinates/time.
- `renderer`: Three.js, LOD/picking, performance and GPU resources.
- `data`: catalogs, SQLite, imports, provenance and reproducible generation.
- `reviewer`: independent architecture, builds/tests, regressions and QA,
  including numerical/browser verification where relevant.

Ownership follows responsibility across backend/frontend. The lead assigns UI
and cross-cutting APIs; owners agree contracts before editing. Implementers
check their work; the reviewer checks it independently.

Use these exact task names. Engage all four roles in stages within lead + three
worker slots; release an implementation slot before review. Create/reuse roles
as needed; recreate live agents in new sessions. Retire old `backend_data`,
`frontend_render`, `qa_review` roles rather than reassigning them.

Give workers fresh, focused context: objective, relevant paths/contracts, owned
files, acceptance criteria and checks. Avoid full conversation/unrelated docs.
Return concise findings, paths, checks/results and risks; link long logs/reports.

One writer per file; coordinate shared changes first. Assign one Docker/browser
owner for stack switches, publication and conflicting checks. Use isolated
QA data; review after implementation. Report checks actually run. The lead
reviews the integrated diff, resolves findings and reports results. Delegate
only the current task; the roadmap does not authorize another stage.

## Non-negotiable physical contract

- Real bodies occupy actual selected-time positions (current time in Now),
  within declared model/source accuracy; see `docs/COORDINATES.md`.
- Separate physical/render coordinates; declare unit, frame/origin, epoch,
  time scale, source, accuracy. Camera/floating origin/LOD preserve centers
  and distances. No nonlinear compression, visibility separation or ID phases.
- Unknown positions/parameters stay null. Synthetic stress/background are not
  measured bodies. Never infer epoch/frame/accuracy from a source label.
- `coordinates/1` = snapshots; `positions/1` = requested-time positions;
  legacy v2 = render coordinates. Never interchange them. Snapshots never feed
  the physical scene; unsupported dates never fall back to snapshots/old dates.
  Validate positions numerically, not just visually.
- Five opted-in DE440s centers: Sun 10, Earth 399, Moon 301, Mercury 199,
  Venus 299. Distinguish barycenters. UTC [2000-01-01, 2027-06-28), pinned to
  IERS C72/table expiry; raw JD TDB bounds in contract. Keep checksum-pinned
  `data/ephemeris/de440s.bsp` and 100 Horizons vectors. Regression tolerance
  is not absolute uncertainty.

## Run and check

```bash
docker compose up --build -d  # http://localhost:5173
docker compose build backend
make test-build
make test
# From frontend/: npm ci; npm run test:coverage; npm run build
python3 tests/browser_physical_mcp.py --catalog 3471
```

Use `-w /app` (image WORKDIR `/app/backend`). One-off commands must not start
with `uvicorn`: it triggers catalog preparation. Backend :8000 is internal;
frontend nginx proxies /api, dev Vite proxies to 127.0.0.1:8000.

Test scenes: `make scene SCENE=sectors|s100k|legacy` on :5174; stop with
`make scene-down`. Ordinary compose stays on :5173, health3471. All test services
use `tests/docker/compose.yml`; unit/acceptance projects and volumes are separate.
Never delete the ordinary volume for QA. Remove only task-created reports,
screenshots, generated stress data and temporary environments/caches. Retain
test sources, numeric fixtures, lockfiles, MCP and BSP.

## Ownership and pitfalls

- `data/catalog.py`: public catalog API/JSON I/O; `catalog_schema.py`: validation;
  `catalog_binary.py` / `catalog_binary_v2.py`: legacy codecs.
- `data/source_registry.py`, `backend/position_api.py`, `data/ephemeris.py`:
  opted-in capabilities/offline positions; `docs/SOURCES.md`.
  `backend/position_work.py`: 4 workers, no backlog, 8s HTTP deadline;
  timed-out native work keeps its slot until actual return.
- `data/physical_hierarchy.py`, `frontend/src/physical/`: default scene,
  Float64 centers, linear GPU transform; `docs/HIERARCHY.md`. One physical
  sector today; general 3.3/3.8 remain open. Legacy: `/?scene=legacy`.
  Opt-in SQLite synthetic S-100k uses this path: `docs/S100K.md`,
  `make scene SCENE=s100k`. Hardware milestone remains open.
- `backend/sector_api.py`, `data/sectors.py`: bounded snapshot API/index;
  `docs/SECTORS.md`. `at` always 422. `frontend/src/data/sectorStore.js` reads
  bounded snapshot cards only.
- `data/publication.py`: shared locks/fsync and RevisionConflict;
  `incremental_region.py`: bounded family/cell updates.
- `streaming_catalog.py`, `streaming_binary.py`, `incremental_catalog.py`:
  bounded JSON→SQLite/patch preparation; full legacy publication stays O(N).
  `data/import_sbdb.py`: bounded NASA/JPL SBDB asteroid HTTP→staging→atomic
  runtime SQLite, manifest, provenance, explicit owned deletes; 3.7-A accepted.
  Old online list builder remains compatible; limited local writer accepted,
  full 3.7-B open. `backend/prepare_runtime.py` runs separately. Runtime
  `CATALOG` is DiskCatalog; never fill test-only `catalog_index()` in production.
- `backend/entrypoint.py`: offline opens working SQLite/copies pinned bootstrap;
  published requires existing ASTROVERSE_SECTOR_PATH; online/existing require
  CLI preparation. `tests/test_api.py` pins catalog_seed.json; unittest ignores
  smoke_*.py.
- HTTP: filtered legacy 4096 objects/8 MiB; snapshot pages 512/2 MiB;
  sector/filtered caches 8 MiB each. Full legacy routes stream. ETag handles
  weak W/, lists, *, percent-encoded Cyrillic. nginx gzip is chunked: assert
  encoding + decoded body, not Content-Length.
- Never mutate shared `bodies/resources.js` resources or WeakMap `scaleCatalog`
  rows. Composition changes preserve WebGLRenderer.
- MCP runners use installed Chrome DevTools MCP. Legacy Playwright uses system
  Chrome, stack3471/stack100k markers (not SMOKE_STRESS). Private React probes
  may need React-upgrade fixes. SwiftShader fps is not GPU fps; stress needs
  DOM-click/longer waits. Details: `tests/README.md`.
