# Проверки Astroverse

Результаты и четыре сводных machine reports — [TEST_COVERAGE](../docs/TEST_COVERAGE.md).
Контракты — документы архитектуры, история — [HISTORY](../docs/HISTORY.md).
Временные JSON/screenshots пишите в системный temp и удаляйте после переноса
нужных результатов. Test sources, numerical fixtures, BSP и lockfiles сохранять.

## Backend/frontend/CI

```bash
docker compose build backend
docker compose run --rm --no-deps -w /app backend python -m unittest discover -s tests -t . -v
docker compose run --rm --no-deps -w /app backend sh -c '
  python -m pip install --target /tmp/coverage -r tests/requirements-coverage.txt &&
  PYTHONPATH=/tmp/coverage python -m coverage run -m unittest discover -s tests -t . &&
  PYTHONPATH=/tmp/coverage python -m coverage report &&
  PYTHONPATH=/tmp/coverage python -m coverage report --include=data/sectors.py --fail-under=100
'
# Из frontend/:
npm ci
npm run test:coverage
npm run build
```

`-w /app` обязателен: image WORKDIR=/app/backend. One-off command не начинать
сuvicorn(запускает preparation). unittest не собирает smoke_*.py.
Backend coverage/branches≥95%,sectors100%; frontend statements/lines/functions/
branches≥95/96/96/85. Unit canvas/WebGL mocked, shader/GPU/fps проверяются отдельно.

## Обычный HTTP/WebGL через Chrome MCP

Установленные системный Chrome и chrome-devtools-mcp; Python Playwright не нужен.
Работающий обычный compose:5173,health3471:

```bash
docker compose up --build -d
python3 tests/browser_physical_mcp.py --catalog 3471
python3 tests/browser_lod_mcp.py --catalog 3471
python3 tests/browser_positions_recovery_mcp.py --catalog 3471
python3 tests/browser_latency_mcp.py --catalog 3471
python3 tests/browser_time_bounds_mcp.py --catalog 3471
python3 tests/browser_navigation_mcp.py --report /tmp/astroverse-navigation.json
python3 tests/browser_navigation_regions_mcp.py --report /tmp/astroverse-regions.json
python3 tests/browser_depth_mcp.py --report /tmp/astroverse-depth.json
python3 tests/browser_mcp.py --catalog 3471 --report /tmp/astroverse-legacy.json
```

Physical: точные UTC/центры, search/cards/source growth/renderer reuse.
LOD: hysteresis/picking/drag/Retina. Recovery: revision races/retry409/errors.
Latency/time bounds: Now/jitter/пауза/дата/ускорение/реверс и границы UTC.
Navigation:6DoF/refocus/rebase/hidden tab и 12resource cycles. Regions:
все 5 центров у Земли, Меркурий после удаления>200 млнkm. Depth: readPixels/
передний picking/L0/L1/оба порядка/точные полюса/native drag. Legacy: v2/gzip/
ETag,views/search/follow/virtualization/resources.

MCP click/fill/press_key — настоящие UI actions. `chrome_hold.mjs` нужен для
trusted CDP held keys/drag/wheel/click: press_key не задаёт длительность.
Private React probes только читают данные/оборачивают timing; при upgrade React
могут потребовать обновления. Итоговое положение камеры не присваивается.
Для hidden-tab runner временно отключает MCP focus emulation, читает настоящий
background target через CDP и подключается обратно; document.hidden не подменяется.

`complete` и `budget_passed` раздельны. Navigation CPU FAIL сохраняет отчёт и
возвращает ненулевой exit. Screenshots MCP экспортировать внутрь системного
`tempfile.gettempdir()`(на macOS обычно /var/folders/.../T,не /tmp).
Chrome/profile закрываются в finally. SwiftShader — функциональность, не GPU fps.

## Synthetic physical S-100k

Изолированный SQLite/HTTP проект:5174,100×1000 stationary центров. Никакие
synthetic routes/bodies не добавляются в production; [профиль/бюджеты](../docs/S100K.md).
Не запускать builds/coverage/другие browser tests одновременно с benchmark.

```bash
ASTROVERSE_PORT=5174 ASTROVERSE_BIND=127.0.0.1 docker compose -p astroverse-s100k-fixture -f docker-compose.yml -f docker-compose.s100k-test.yml up --build -d
python3 tests/browser_s100k_dynamic_mcp.py --hardware --seconds 5 --cycles 12 --report /tmp/astroverse-s100k-dynamic.json
python3 tests/report_s100k_dynamic.py /tmp/astroverse-s100k-dynamic.json --output /tmp/astroverse-s100k-assessment.json
# Функциональные проверки отдельно от чистых интервалов:
python3 tests/browser_s100k_mcp.py --hardware --seconds 3 --report /tmp/astroverse-s100k-functional.json
python3 tests/browser_s100k_mcp.py --rebase-only --report /tmp/astroverse-s100k-rebase.json
docker compose -p astroverse-s100k-fixture -f docker-compose.yml -f docker-compose.s100k-test.yml down
docker compose up --build -d
curl -fsS http://localhost:5173/api/health  # objects3471
```

Dynamic runner проверяет health100000 до Chrome, сохраняет complete=false/error
при отказе. `--hardware` убирает software flags; проверяйте фактический renderer.
Framebuffers1920×1080/DPR1; headless RAF — не вывод монитора/GPU fence.
3s steady warmup,1s перед остальными окнами; seconds — добавочное наблюдение
после действий, не длительность всего окна. Отдельные steady/picking/flight/
rebase-eviction/Now/ускорение/реверс и каждый из 12 циклов. После каждого окна —
полные identities/numeric/frustum и bounded resource checks, вне замера.

Внутри окон buffers≤20000samples/metric. CPU performance.now spans включают
preemption/GC; micro-loop оценивает нижний overhead, не вычитается из результата.
HTTP Resource Timing отдельно от decode CPU; manager selection/prepare/display
elapsed включают ожидание. Coalescing до admission отдельно не измерен.
GPU driver RAM/upload completion неизвестны. Согласованный frame p95≤16.8ms,
p99≤33.334ms; все остальные исходные бюджеты сохранены. Поле fraction_60hz в
raw reports всё ещё буквально считает≤16.667ms, не заменяет p95.

Functional runner проверяет 100k центров/границы секторов/совпадения/время/
partial failure/revision conflict/cycles; его action timings с полными scans
не являются чистым dynamic benchmark. Непустой rebase отдельно сверяет биты
всех 100k и 16screen projections. Assessment не меняет исходный файл;
`python3 tests/report_s100k_dynamic.py docs/s100k_report.json` проверяет
сохранённый stress по действующим бюджетам, без повторного запуска.

## Многосекторный fixture32×64

```bash
ASTROVERSE_PORT=5174 ASTROVERSE_BIND=127.0.0.1 docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml up --build -d
python3 tests/browser_sectors_mcp.py --report /tmp/astroverse-sectors.json
python3 tests/browser_navigation_mcp.py --url http://localhost:5174 --synthetic --report /tmp/astroverse-navigation-synthetic.json
node --expose-gc tests/benchmark_sector_manager.mjs
docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml down
docker compose up --build -d
```

Health synthetic:true/objects0,2048resident/2016computed/32unknown. Runner проверяет
48load/evict/return, hysteresis, numeric transforms, UTC/JD/revisions, retry409,
partial/mixed JD/timeout и отдельный admission2048→ошибка→явное восстановление.
Limits/timing — [PHYSICAL_LOD](../docs/PHYSICAL_LOD.md). Native solver guard
отдельно проверяется tests/test_position_http.py и test_position_work.py.
Request correlation: X-Astroverse-Client/Selection/Request, sink не хранит историю;
nginx logs и provider traces сопоставляются с учётом cancel до API.

## Прямой SBDB import и нагрузка БД

Из корня, Python3.12+ с backend requirements; либо Docker с-w/app и постоянным
общим volume для output SQLite. Без volume результат run--rm теряется.

```bash
python -m backend.prepare_runtime data/catalog_seed.json data/import.runtime.sqlite
sqlite3 data/import.runtime.sqlite "select value from metadata where key='catalog_revision';"
python -m data.import_sbdb data/import.runtime.sqlite --expected-revision HEX --limit 400
# Опции expected-sha256/delete-id/timeout/retries/max-bytes: --help
ASTROVERSE_CATALOG_MODE=published ASTROVERSE_SECTOR_PATH=data/import.runtime.sqlite python -m uvicorn backend.app:app
docker compose run --rm --no-deps -w /app backend python -m unittest tests.test_import_sbdb tests.test_import_http -v
docker compose run --rm --no-deps -w /app -v "$PWD/docs:/evidence" backend python -m tests.benchmark_import --output /evidence/import_budget_report.json
```

Пример создаёт отдельную БД, seed не заменяет. HEX берётся без JSON-кавычек.
HTTP fixture `sbdb_fixture.py` пишет строки потоком; `import_http.py` используется
тестами и benchmark для настоящего API без исходного JSON. Эти helpers нужны.
Проверяются truncation/redirect/count/token/errors, writers/readers, explicit
owned deletes, SIGKILL/restart и atomic publication. Бюджеты 100k/1 млн:
RSS≤384MiB,рост≤64MiB,время≤300/1800s,диск≤1/10GiB.
Измерения importer/fixture/API раздельны; sampled disk включает unlinked spools
через/proc/PID/fd, может пропустить короткий пик. Legacy/graph остаются O(N).

## Численные fixtures и отдельные benchmarks

Сохранять horizons_centers.json(100 векторов),physical_hierarchy_synthetic.json,
binary_catalog.json(Python↔JS),utc_leap_support.json и sbdb_field_units.json.
Snapshot/registry неизвестность не заменяется данными из другого контракта.

```bash
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_backend build data/catalog_seed.json
docker compose exec -w /app backend python -m tests.benchmark_backend runtime
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_streaming --million
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_registry
node --expose-gc tests/benchmark_hierarchy.mjs
node --expose-gc tests/benchmark_physical_lod.mjs
```

Последний script объединяет retained heap/ArrayBuffers и apply/LOD/picking timings
на 4096 строках. Это Node/V8, не browser/GPU RAM. Первый запрос не является SLA.
SBDB benchmark и source/token/graph contracts — соответствующие test_*.py.
Аудит: npm audit; pip-audit ставить отдельно в temp, не в production requirements.

## Legacy100k и Playwright smoke

```bash
python3 data/gen_catalog_100k.py
docker compose -f docker-compose.yml -f docker-compose.100k.yml up --build -d
# MCP с --catalog100000; затем восстановить обычный compose/health3471.
python3 -m venv /tmp/astroverse-smoke-env
/tmp/astroverse-smoke-env/bin/python -m pip install playwright pytest
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -m stack100k -v
docker compose up --build -d
```

Для обычного стека marker stack3471. Тестируется `/?scene=legacy`, используются
системный Chrome и probe из common.py; путь CHROME задаёт conftest.py.
SMOKE_HEADED=1 включает окно. Headless SwiftShader fps не аппаратные;
100k использует DOM-click/длинные waits. gzip проверяется encoding+decoded body,
не chunked Content-Length. Полный objects_100k.json генерируется, не коммитится.
Это legacy cards/render positions, не 100k реальных requested-time положений.
