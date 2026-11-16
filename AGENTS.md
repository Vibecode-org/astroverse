# Astroverse

React + Three.js / FastAPI, Docker. Runtime opens persistent SQLite; clean install copies the pinned bootstrap.
Start with this file and the relevant document; do not load every document by
habit. Current sequence/status: `ROADMAP.md`; verification: `docs/TEST_COVERAGE.md`.
Commands and browser/benchmark details: `tests/README.md`.
Long-term goal: all known astronomical bodies as of each data refresh, with
source coverage/gaps recorded. Million-row and S-100k milestones are neither
catalog size caps nor proof of complete coverage. Unknown physics stays null.
Target production storage: all working body/model data lives and updates in the
DB. Fixed JSON files must not be the primary body catalog; startup must not
require a full objects.json. JSON remains valid for API, fixtures and tooling.
Production build/startup require no full catalog JSON. Seed remains test/tooling;
verify consumers before removing fixtures, configs or lockfiles.

## Team workflow

The primary agent acts as team lead. The user explicitly requests sub-agent
delegation for substantive tasks to keep the primary context focused. Delegate
bounded investigation, implementation and review; do not do all work in the
primary conversation. Small, isolated edits may be handled directly.

- Team lead: clarify scope, split work, assign file ownership, resolve shared
  contracts, integrate changes and take responsibility for final verification.
- `physicist`: physical semantics, JPL Horizons, ephemerides,
  coordinates and simulation time.
- `renderer`: Three.js rendering, LOD/picking, performance and GPU resources.
- `data`: catalogs, SQLite, imports, sources/provenance and deterministic,
  reproducible generation.
- `reviewer`: independent architecture review, builds, tests, regression
  analysis and QA, including numerical/browser verification where relevant.

Roles span backend and frontend; ownership follows the responsibility above,
not the directory. The lead assigns UI and cross-cutting APIs for each task;
owners agree on shared contracts before implementation. Each implementer
checks their own changes; the reviewer independently checks the resulting work.

Create or reuse these roles as needed within the available agent limit
(currently lead + three workers). Engage the four worker roles in stages;
release an implementation slot for the reviewer once the relevant work is
ready. Do not schedule four workers simultaneously. Roles persist in these
instructions; live agents must be recreated in a new session.
Use the exact agent task names `physicist`, `renderer`, `data`, and `reviewer`.
Create each role with fresh, focused context; retire the old `backend_data`,
`frontend_render`, and `qa_review` agents rather than reassigning their roles.
Give workers fresh, focused context:
objective, relevant paths/contracts, owned files, acceptance criteria and
required checks. Avoid copying the full conversation or reading unrelated docs.
Workers return concise findings, changed paths, checks/results and unresolved
risks; keep long logs and reports in files and link to them.

Assign one writer per file; coordinate cross-cutting changes before editing.
All agents share the workspace and Docker/browser resources: one designated
owner switches stacks, publishes databases or runs conflicting browser checks.
Use isolated temporary data for independent checks. Schedule QA after the
relevant changes are ready; report which checks actually ran. The lead reviews
the integrated diff, resolves findings and reports the outcome to the user.
Delegate only work within the user's current task; the roadmap is context,
not authorization to start another stage.

## Non-negotiable physical contract

- Real bodies occupy actual positions at the selected time (current time in
  Now), within declared source/model accuracy. See `docs/COORDINATES.md`.
- Separate physical and render coordinates; declare unit, frame/origin, epoch,
  time scale, source, accuracy. Camera/floating origin/LOD preserve centers and
  distances. No nonlinear compression, separation for visibility or ID phases.
- Unknown positions/parameters remain null. Synthetic stress/background are
  not measured bodies. Never infer epoch/frame/accuracy from a source label.
- `coordinates/1` = catalog snapshots; `positions/1` = requested-time positions;
  legacy v2 = render coordinates. Do not reinterpret one as another. Snapshots
  never feed the physical scene; unsupported dates never fall back to snapshots
  or a previous date. Validate positions numerically, not just screenshots.
- Five opted-in DE440s centers: Sun 10, Earth 399, Moon 301, Mercury 199,
  Venus 299. Barycenters differ from body centers. UTC [2000-01-01, 2027-06-28)
  pinned to IERS C72/table expiry; raw JD TDB
  bounds in contract. Keep checksum-pinned `data/ephemeris/de440s.bsp` and
  100 Horizons vectors. Regression tolerance is not absolute uncertainty.

## Run and check

```bash
docker compose up --build -d  # http://localhost:5173
docker compose build backend
make test-build
make test
# From frontend/: npm ci; npm run test:coverage; npm run build
python3 tests/browser_physical_mcp.py --catalog 3471
```

`-w /app` is required (image WORKDIR is /app/backend). One-off commands must
not start with `uvicorn`, which triggers catalog preparation. Backend :8000
is internal; frontend nginx proxies /api. Dev Vite proxies to 127.0.0.1:8000.
Test scenes use `make scene SCENE=sectors|s100k|legacy` on :5174; stop with
`make scene-down`. Ordinary compose remains on :5173 with health3471.
All test services live in `tests/docker/compose.yml`; unit and acceptance have
separate project names/volumes. Never delete the ordinary volume for QA.
Remove only task-created reports, screenshots, generated stress data, temporary
environments/caches; retain test sources, numeric fixtures, lockfiles, MCP, BSP.

## Ownership and pitfalls

- `data/catalog.py` retains the public catalog API/JSON I/O; `catalog_schema.py`
  owns validation, `catalog_binary.py` / `catalog_binary_v2.py` own legacy codecs.
- `data/source_registry.py` / `backend/position_api.py` / `data/ephemeris.py`:
  opted-in capabilities and offline positions; `docs/SOURCES.md`.
  `backend/position_work.py`: 4 admitted workers, no backlog, 8s HTTP deadline;
  a timed-out native solver keeps its slot until it actually returns.
- `data/physical_hierarchy.py` / `frontend/src/physical/`: default scene,
  Float64 centers, linear GPU transform; `docs/HIERARCHY.md`. One physical
  sector today; general 3.3/3.8 remain open. Legacy is `/?scene=legacy`.
  Opt-in SQLite synthetic S-100k uses the same path: `docs/S100K.md`;
  `make scene SCENE=s100k`. Hardware milestone remains open.
- `backend/sector_api.py`, `data/sectors.py`: bounded snapshot API/index;
  `docs/SECTORS.md`. `at` always 422. `frontend/src/data/sectorStore.js`
  reads bounded snapshot cards only.
- `data/publication.py`: shared publication locks/fsync and RevisionConflict;
  `incremental_region.py`: bounded family/cell updates.
- `streaming_catalog.py`, `streaming_binary.py`, `incremental_catalog.py`:
  bounded JSON→SQLite/patch preparation; full legacy publication remains O(N).
  `data/import_sbdb.py`: bounded direct SBDB asteroid HTTP→staging→atomic
  runtime SQLite, manifest, explicit owned deletes; 3.7-A accepted. The old
  online list builder remains for compatibility; limited local writer is accepted, full 3.7-B remains open.
  `backend/prepare_runtime.py` runs separately. Runtime `CATALOG` is DiskCatalog;
  never populate the test-only list `catalog_index()` from production data.
- `backend/entrypoint.py`: offline opens working SQLite/copies pinned bootstrap;
  published requires existing ASTROVERSE_SECTOR_PATH. online/existing require CLI preparation.
  `tests/test_api.py` pins catalog_seed.json. unittest ignores smoke_*.py.
- HTTP limits: filtered legacy 4096 objects/8 MiB; snapshot pages 512/2 MiB;
  separate sector/filtered caches 8 MiB each. Full legacy routes stream.
  ETag must handle weak W/, lists, * and percent-encoded Cyrillic queries.
  nginx gzip is chunked: assert encoding + decoded body, not Content-Length.
- Shared resources in `bodies/resources.js` and WeakMap `scaleCatalog` rows
  must not be mutated. Composition changes must preserve WebGLRenderer.
- MCP runners use installed Chrome DevTools MCP. Legacy Playwright uses system
  Chrome, stack3471/stack100k markers (not SMOKE_STRESS). Private React probes
  may need adjustment after React upgrades. SwiftShader fps is not GPU fps;
  stress uses DOM-click and longer waits. Details: `tests/README.md`.
