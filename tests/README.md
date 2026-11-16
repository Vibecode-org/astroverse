# Проверки Astroverse

Результаты — [TEST_COVERAGE](../docs/TEST_COVERAGE.md). Обычный compose остаётся
на :5173; все тестовые сервисы описаны в [docker/compose.yml](docker/compose.yml).
`make` показывает команды. Требуются Docker Compose v2 и Make.

## Основные команды

```bash
make test                      # build + все backend unittest
make coverage                  # branches ≥95%, sectors 100%
make unit ARGS='run --rm unit python -m unittest tests.test_catalog_backup -v'
# Из frontend/: npm ci; npm run test:coverage; npm run build
```

Unit image содержит fixtures; production image — код/config/BSP/pinned SQLite
без полного каталожного JSON. Unit не подключает рабочий volume. CI использует
`make coverage`, frontend thresholds statements/lines/functions/branches ≥95/96/96/85.
Runtime one-offs требуют `-w /app`; команда `uvicorn` запускает подготовку API.
`unittest` не собирает `smoke_*.py`.

## Тестовые сцены

```bash
make scene SCENE=sectors        # 32×64 HTTP fixture
make scene SCENE=s100k          # 100×1000 physical synthetic
make scene SCENE=legacy         # подготовит отдельную legacy SQLite100k
make scene-down                # остановить сцену, сохранить test volumes
```

Открывайте http://localhost:5174 (legacy: `/?scene=legacy`). `SCENE` выбирает
ровно один сценарий; смена останавливает прежнюю тестовую сцену. Порт меняется
через `ASTROVERSE_TEST_PORT`. Проекты `astroverse-tests`, `astroverse-scene`,
`astroverse-acceptance` отделены от обычного приложения; штатные down сохраняют
volumes. Основной compose не переключается и не получает synthetic данные.

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
Секторы: после `make scene SCENE=sectors` запустите
`python3 tests/browser_sectors_mcp.py --report /tmp/astroverse-sectors.json`.

```bash
make scene SCENE=s100k
python3 tests/browser_s100k_mcp.py --report /tmp/astroverse-s100k-functional.json
python3 tests/browser_s100k_mcp.py --rebase-only --report /tmp/astroverse-rebase.json
python3 tests/browser_s100k_dynamic_mcp.py --hardware --seconds 5 --cycles 12 --report /tmp/astroverse-dynamic.json
python3 tests/report_s100k_dynamic.py /tmp/astroverse-dynamic.json
make scene-down
```

Performance: без параллельных builds/tests; проверяйте реальный renderer.
SwiftShader — функциональность. Headless RAF/CPU submission не GPU fence,
monitor presentation или driver memory. Функциональные полные scans выполняются
вне timing windows. `complete` и прохождение бюджетов различаются; неполный
run не PASS. [Профиль и бюджеты](../docs/S100K.md).

MCP действия настоящие; `chrome_hold.mjs` задаёт held keys/drag через CDP.
React probes могут требовать адаптации после React upgrade. Сохраняйте renderer/
resources/listeners; legacy baseline — после CDN loads/errors и GPU прогрева
всех масштабов. Screenshots пишите в `tempfile.gettempdir()`, логи — вне repo.

Legacy Playwright использует system Chrome; установите playwright/pytest во
временный venv. `SMOKE_URL=http://localhost:5174 python -m pytest tests/browser_smoke/ -m stack100k -v`
проверяет изолированную legacy-сцену; без переменной используется :5173/stack3471.
Markers сверяют реальный health count, `SMOKE_HEADED=1` включает headed Chrome.

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

`/backups` находится вне volume: host `ASTROVERSE_BACKUP_DIR`, по умолчанию
`/tmp/astroverse-acceptance`. Нужен новый writable uid10001 каталог/bundle для
каждого прогона; existing backup не перезаписывается. `make acceptance-up`
создаёт каталог, права уже существующего не меняет. Здесь только synthetic patch.
Проверяются bytes БД, порядок/cards/metadata и9 API responses, ETag и5 DE440s центров.

Для restart/recreate повторите compare после `restart runtime` и
`up -d --force-recreate --wait`. Иной готовый runtime image выбирается через
`ASTROVERSE_DELIVERY_IMAGE=TAG make acceptance ARGS='up -d --force-recreate --wait'`;
он должен содержать действительно другую pinned bootstrap (helper
`tests.prepare_delivery_variant`), сохранив прежнюю рабочую БД. Отдельный
startup probe `/app/check_startup_container.py patch|verify` запускается на
свежем isolated volume вместо delivery patch.
Операционные backup/restore/migration — [STARTUP](../docs/STARTUP.md).

## Benchmarks и fixtures

```bash
make unit ARGS='run --rm unit python -m tests.benchmark_backup --count 100000'
make unit ARGS='run --rm unit python -m tests.benchmark_incremental --count 1000000'
python3 -m tests.benchmark_incremental --assess docs/reports/incremental_budget_report.json
python3 tests/report_s100k_dynamic.py docs/reports/s100k_report.json
```

Каждый размер — свежий процесс, вывод/temporary данные вне repo. Другие entrypoints:
`tests.benchmark_startup` (readiness/peak/API RSS), `tests.benchmark_import`
(SBDB fixture/importer/API отдельно), `tests.benchmark_streaming`,
`tests.benchmark_backend`, `tests.benchmark_registry`,
`tests/benchmark_{hierarchy,physical_lod,sector_manager}.mjs`; параметры — `--help`/docstring.
Copy/hash/integrity/legacy O(N) учитывать отдельно; sampled disk может пропустить
пик/unlinked files, SQLite integrity RSS не означает полный Python list.
Incremental `--baseline` годится только для pre-sprint writer4fe4263.

Сохранять `tests/fixtures/` (100 Horizons vectors, binary Python↔JS, hierarchy,
UTC leap support, SBDB units), BSP, lockfiles и test sources. `sector_provider`,
`s100k_provider`, `sbdb_fixture`, `import_http` нужны регрессиям, в runtime не входят.
Постоянные отчёты — [docs/reports](../docs/reports), с датой/версией/методом/
ограничениями; raw logs/screenshots/coverage не коммитить.
