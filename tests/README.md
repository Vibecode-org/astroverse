# Проверки Astroverse

Результаты — [TEST_COVERAGE](../docs/TEST_COVERAGE.md). Обычный compose — : 5173;
тестовые сервисы — [docker/compose.yml](docker/compose.yml).
`make` показывает команды. Требуются Docker Compose v2 и Make.

## Основные команды

```bash
make test                      # build + все backend unittest
make coverage                  # branches ≥95%, sectors 100%
make unit ARGS='run --rm unit python -m unittest tests.test_catalog_backup -v'
# Из frontend/: npm ci; npm run test:coverage; npm run build
```

Unit image содержит fixtures; production — код/config/BSP/pinned SQLite без полного
каталожного JSON. Unit без рабочего volume. CI:
`make coverage`, frontend thresholds statements/lines/functions/branches ≥95/96/96/85.
Runtime one-offs: `-w /app`; `uvicorn` запускает подготовку API.
`unittest` не собирает `smoke_*.py`.

## Тестовые сцены

```bash
make scene SCENE=sectors        # 32×64 HTTP fixture
make scene SCENE=s100k          # 100×1000 physical synthetic
make scene SCENE=legacy         # подготовит отдельную legacy SQLite100k
make scene-down                # остановить сцену, сохранить test volumes
```

http://localhost:5174 (legacy: `/?scene=legacy`). `SCENE` выбирает один сценарий,
останавливая прежний; порт — `ASTROVERSE_TEST_PORT`. Проекты `astroverse-tests`, `astroverse-scene`,
`astroverse-acceptance` изолированы от обычного приложения; штатные down сохраняют
volumes. Основной compose не переключается, synthetic данные не получает.

## Chrome / HTTP / численные проверки

Нужны системный Chrome и установленный Chrome DevTools MCP. Обычная сцена:

```bash
python3 tests/browser_physical_mcp.py --catalog 3471
python3 tests/browser_mcp.py --catalog 3471 --report /tmp/astroverse-legacy.json
python3 tests/browser_navigation_mcp.py --report /tmp/astroverse-navigation.json
python3 tests/browser_depth_mcp.py --report /tmp/astroverse-depth.json
```

Остальные runners: `browser_lod_mcp.py` (picking/Retina/hysteresis),
`browser_positions_recovery_mcp.py` (409/errors), `browser_latency_mcp.py`
(Now/jitter), `browser_time_bounds_mcp.py` (UTC),
`browser_navigation_regions_mcp.py` (Earth/Mercury handoff).
Секторы: после `make scene SCENE=sectors` —
`python3 tests/browser_sectors_mcp.py --report /tmp/astroverse-sectors.json`.

```bash
make scene SCENE=s100k
python3 tests/browser_s100k_mcp.py --report /tmp/astroverse-s100k-functional.json
python3 tests/browser_s100k_mcp.py --rebase-only --report /tmp/astroverse-rebase.json
python3 tests/browser_s100k_dynamic_mcp.py --hardware --seconds 5 --cycles 12 --report /tmp/astroverse-dynamic.json
python3 tests/report_s100k_dynamic.py /tmp/astroverse-dynamic.json
make scene-down
```

Performance: без параллельных builds/tests; проверять реальный renderer.
SwiftShader — функциональность. Headless RAF/CPU submission не GPU fence,
monitor presentation или driver memory. Полные functional scans — вне timing
windows. `complete` не означает прохождения бюджетов; неполный run не PASS. [Профиль и бюджеты](../docs/S100K.md).

MCP actions настоящие; `chrome_hold.mjs` — held keys/drag через CDP.
React upgrade может потребовать адаптации probes. Сохранять renderer/
resources/listeners; legacy baseline — после CDN loads/errors и GPU прогрева
всех масштабов. Screenshots — в `tempfile.gettempdir()`, логи — вне repo.

Legacy Playwright: system Chrome, playwright/pytest во временном venv. `SMOKE_URL=http://localhost:5174 python -m pytest tests/browser_smoke/ -m stack100k -v`
проверяет isolated legacy; без переменной — : 5173/stack3471.
Markers сверяют health count; `SMOKE_HEADED=1` — headed Chrome.

## Offline startup и backup/restore acceptance

```bash
make acceptance-up             # seed-free runtime, network:none, отдельный test volume
make acceptance ARGS='exec runtime python /app/check_delivery_container.py --patch --save /backups/working.json'
make acceptance ARGS='exec runtime python -m data.catalog_backup backup /app/data/runtime/catalog.sqlite /backups/working-backup'
# Удаляется ТОЛЬКО volume фиксированного isolated проекта astroverse-acceptance:
make acceptance ARGS='down --volumes'
make acceptance ARGS='run --rm runtime python -m data.catalog_backup restore /backups/working-backup /app/data/runtime/catalog.sqlite'
make acceptance-up
make acceptance ARGS='exec runtime python /app/check_delivery_container.py --expect /backups/working.json'
make acceptance-down
```

`/backups` вне volume: host `ASTROVERSE_BACKUP_DIR`, default
`/tmp/astroverse-acceptance`. Каждый прогон — новый writable uid10001
каталог/bundle; existing backup не перезаписывается. `make acceptance-up`
создаёт каталог без изменения существующих прав. Здесь только synthetic patch.
Проверяются DB bytes, порядок/cards/metadata, 9 API responses, ETag, 5 DE440s центров.

Restart/recreate: повторить compare после `restart runtime` и
`up -d --force-recreate --wait`. Иной готовый runtime image:
`ASTROVERSE_DELIVERY_IMAGE=TAG make acceptance ARGS='up -d --force-recreate --wait'`;
Требуется другая pinned bootstrap (helper `tests.prepare_delivery_variant`)
с сохранением рабочей БД. Отдельный startup probe
`/app/check_startup_container.py patch|verify` — на свежем isolated volume
вместо delivery patch.
Операционные backup/restore/migration — [STARTUP](../docs/STARTUP.md).

## Benchmarks и fixtures

```bash
make unit ARGS='run --rm unit python -m tests.benchmark_backup --count 100000'
make unit ARGS='run --rm unit python -m tests.benchmark_incremental --count 1000000'
python3 -m tests.benchmark_incremental --assess docs/reports/incremental_budget_report.json
python3 tests/report_s100k_dynamic.py docs/reports/s100k_report.json
```

Каждый размер — свежий процесс; вывод/temporary данные вне repo. Entry points:
`tests.benchmark_startup` (readiness/peak/API RSS), `tests.benchmark_import`
(SBDB fixture/importer/API отдельно), `tests.benchmark_streaming`,
`tests.benchmark_backend`, `tests.benchmark_registry`,
`tests/benchmark_{hierarchy,physical_lod,sector_manager}.mjs`; параметры — `--help`/docstring.
Copy/hash/integrity/legacy O(N) — отдельно; sampled disk может пропустить
пик/unlinked files, SQLite integrity RSS не означает полный Python list.
Incremental `--baseline` годится только для pre-sprint writer4fe4263.

Сохранять `tests/fixtures/` (100 Horizons vectors, binary Python↔JS, hierarchy,
UTC leap support, SBDB units), BSP, lockfiles и test sources. `sector_provider`,
`s100k_provider`, `sbdb_fixture`, `import_http` нужны регрессиям, в runtime не входят.
Отчёты — [docs/reports](../docs/reports), с датой/версией/методом/ограничениями;
raw logs/screenshots/coverage не коммитить.

## SQLite/API 6.1–6.3 load acceptance

```bash
mkdir -p -m 777 /tmp/astroverse-api-load
make load                      # nonzero retains report on diagnostic budget failure
make load-verify               # untimed content oracles, same regenerated checksums
# Compact report: /tmp/astroverse-api-load/api_load_report.json
# Short diagnostic only (not acceptance):
make load LOAD_ARGS='--counts 15000 --concurrency 1 --repeats 1 --requests 8 --sustained-seconds 1'
```

The existing unit image runs a real backend subprocess on private temporary
SQLite fixtures, preserving production volume/bootstrap. Predeclared matrix:
100k/1m, concurrency 1/4/16, search/card/nearby/page/locate, empty/dense/sparse/large
parent family, page limits, sequential/repeated load. Cold=fresh backend/empty
application caches, **not** flushed OS page cache; warm=endpoint pass before timing.
Unchanged limits: page 512/2MiB, nearby 128, search 500, filtered 4096/8MiB, sector cache 8MiB,
shared filtered/search cache 8MiB. Search keys: semantic revision/normalized query/
effective limit. Identical concurrent fills share computation; distinct keys
progress independently. Transient fill coordination≤active sync workers,
separate from payload byte budget. These are not backend RSS limits.
Latency/RSS remain observations, not new performance SLAs. Predeclared diagnostics:
p95≤500ms, p99≤1500ms, max≤10s, worker RSS≤512MiB, late-window RSS range≤32MiB,
readiness≤60s, fixture≤300s, writer≤180s. Follow-up keeps thresholds/matrix;
each separate concurrency 16 sustained run grows from 60s to 300s (explicit Make
default, declared before rerun). Late-half RSS range is heuristic, not asymptotic proof.
Publication/copy/hash/integrity/full exports are separate O(N) work. Report driver/
fixture generation memory separately from sampled backend RSS. Report unrelated
pre-existing frontend working-copy failures; partial checks are not acceptance.

`load-verify` appends independent bounds/search/card/locate/validation oracles
to the same report, preserving timing source hashes. Temporary-directory cleanup
removes generated SQLite; regeneration checks logical SHA/revision. Another 32
distinct sequential keys have exact fixture-derived content oracles and separate
uncached latency, not 16-way distinct-query acceptance; novel substring searches
remain O(N). Unit tests check 200-key eviction within shared budget, errors waking
waiters, publication changes preventing stale search reuse. Scope: snapshot/catalog
API, not massive positions.

## Temporal physical streaming slice

[Contract and budgets](../docs/PHYSICAL_STREAMING.md); one compact result:
[physical_streaming_report.json](../docs/reports/physical_streaming_report.json).
Five real DE440s centers are separate from explicitly synthetic affine scaling.
Existing test image/admission pool/manager/layer/MCP runner are reused; temporal
fixtures add fixed-member sectors/conservative time envelopes.

```bash
make temporal                  # 100k/1M; 3 fresh processes each; 180s final window
# Optional short diagnostic, not acceptance:
make temporal TEMPORAL_ARGS='--counts 100000 --repeats 1 --requests 8 --seconds 0'
# Build the actual production manager/layer WebGL harness outside the repo:
frontend/node_modules/.bin/esbuild tests/benchmark_temporal_streaming.mjs --bundle --format=iife --outfile=/tmp/astroverse-temporal/temporal-harness.js
make scene SCENE=temporal      # isolated :5174; existing ordinary :5173 retained
python3 tests/browser_temporal_mcp.py --count 100000 --seconds 120 --report /tmp/astroverse-temporal/browser-100000.json
ASTROVERSE_TEMPORAL_COUNT=1000000 make scene SCENE=temporal
python3 tests/browser_temporal_mcp.py --count 1000000 --seconds 120 --report /tmp/astroverse-temporal/browser-1000000.json
python3 -m tests.benchmark_temporal_streaming --directory /tmp/astroverse-temporal --merge-browser /tmp/astroverse-temporal/browser-100000.json /tmp/astroverse-temporal/browser-1000000.json
make scene-down
```

If frontend dependencies are absent, run `npm ci`. `ASTROVERSE_TEMPORAL_DIR`
overrides fixture/report mount (default `/tmp/astroverse-temporal`); use it for
both harness build/report paths. Fixtures stay there for Chrome/reproducibility,
never in the normal catalog volume. Construction/integrity/fsync/publication are
separate O(N) timings; generator/driver RSS is separate from backend. Fresh process/
application cache does not flush OS page cache. Dense broad phase >16 candidate
sectors→413 without truncation, even if exact spatial tests would remove false positives.

Browser: actual manager→API→Float64 layer→WebGL, independent affine oracles, three
resource cycles, 120s transitions. Render callback CPU=LOD+submission; decode/merge/
apply/long tasks/RAF are separate. All-run cold outliers accompany sustained-phase
distributions. Heap windows/resource counts do not measure GPU driver memory;
SwiftShader is functional evidence, not hardware 60fps. Frontend regressions also
check React clock coalescing/late responses/revision races. Production numerics:
100 Horizons vectors in `tests.test_positions`; `tests.test_temporal_physics`
independently checks swept completeness/seams/tangency/null/reversal/exact
requested-time payloads. New route tests: publication conflicts, malformed index/
model, per-publication interval 422 before 304, native-slot retention after timeout.
