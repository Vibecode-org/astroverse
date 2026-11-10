# Проверки Astroverse

Результаты/числа/ограничения — [TEST_COVERAGE](../docs/TEST_COVERAGE.md).
Ниже команды; тесты/эталоны сохранять, временные отчёты и нагрузочные данные удалять.

## Backend и coverage (Docker)

```bash
docker compose build backend
docker compose run --rm --no-deps -w /app backend \
  python -m unittest discover -s tests -t . -v

docker compose run --rm --no-deps -w /app backend sh -c '
  python -m pip install --target /tmp/coverage -r tests/requirements-coverage.txt &&
  PYTHONPATH=/tmp/coverage python -m coverage run -m unittest discover -s tests -t . &&
  PYTHONPATH=/tmp/coverage python -m coverage report &&
  PYTHONPATH=/tmp/coverage python -m coverage report --include=data/sectors.py --fail-under=100
'
```

`-w /app` обязателен: образ WORKDIR=/app/backend, тесты=/app/tests.
`.coveragerc`: backend/data, branches, общий порог 95%; sectors.py 100% строк/ветвей.
smoke_*.py не собираются unittest (в контейнере нет Playwright/pytest).

## Frontend

Из frontend/: `npm ci`, `npm run test:coverage`, `npm run build`.
Vitest/V8 включает все src JS/JSX; HTML в coverage/index.html. Пороги:
statements 95%,lines 96%,functions 96%,branches 85% (vitest.config.js).
Unit использует canvas stub/замену WebGLRenderer, проверяет настоящие Three.js
ресурсы; GPU/shaders/fps требуют Chrome. .github/workflows/test.yml проверяет
оба coverage и production build на push/PR, browser запускается отдельно.

## Chrome DevTools MCP

Нужны работающий стек :5173, системный Chrome и установленный chrome-devtools-mcp
(проверена 1.12.0). Python runner запускает MCP по stdio и отдельный headless
Chrome/SwiftShader; Playwright/Python-пакеты не нужны.

```bash
docker compose up --build -d
python3 tests/browser_physical_mcp.py --catalog 3471
python3 tests/browser_lod_mcp.py --catalog 3471
python3 tests/browser_positions_recovery_mcp.py --catalog 3471
python3 tests/browser_latency_mcp.py --catalog 3471
python3 tests/browser_time_bounds_mcp.py --catalog 3471
python3 tests/browser_mcp.py --catalog 3471 --report /tmp/astroverse-legacy.json
```

| Runner | Проверка |
|---|---|
| browser_physical_mcp.py | /: UTC/центры, zoom/refocus/обзор, время/возврат, sources pages/ETag, поиск/карточки, synthetic growth9/129/1/0 и 20 cross-sector перестановок без роста GPU/renderer recreation |
| browser_lod_mcp.py | L0/L1 picking/refocus, hysteresis, отсутствие HTTP при движении внутри области, подавление click после drag, Retina pixel ratio=2 |
| browser_positions_recovery_mcp.py | Изолированные ответы: revision race/retry, повторный конфликт, malformed scale, восстановление слоя/отдельная init error; ожидаемые 409 resource errors разрешены, uncaughtJS запрещены |
| browser_latency_mcp.py | Изолированные задержки 200–400 мс; Now, пауза/дата, ускорение/реверс, явный UTC/лаг и ресурсы |
| browser_time_bounds_mcp.py | UI→HTTP→WebGL: январь 2027, последняя поддержанная секунда, исключённая граница UTC, восстановление Now |
| browser_mcp.py | /?scene=legacy: v2/gzip/304, spatial nearby/page/locate/304, виды/LOD, поиск/карточки/follow, виртуализация и ресурсы |

Неверный health/недоступный сервер — ошибка. `--report` сохраняет JSON с
complete:true и путём screenshot; physical/recovery/latency report опционален.
Временные отчёты/скриншоты удалять после переноса измерений в документацию.

## Synthetic 100k и возврат обычного стека

```bash
python3 data/gen_catalog_100k.py
docker compose -f docker-compose.yml -f docker-compose.100k.yml up --build -d
# Те же MCP-команды с --catalog 100000; legacy report — отдельный файл.
# После stress:
docker compose up --build -d
curl -fsS http://localhost:5173/api/health
# Ожидается {"status":"ok","objects":3471}
```

Оба стека используют 5173; generated objects_100k.json не коммитить.
100k — каталог synthetic-карточек, не 100k реальных положений/массовая физика.

## Несколько физических секторов через HTTP

Opt-in fixture работает отдельным Docker-проектом на :5174, не добавляет
маршрутов/тел в обычный API :5173. Health: `synthetic:true, objects:0`. 32 сектора по 64 искусственные
записи, по одному unknown/null в секторе. Это не NASA и не массовая астрометрия.

```bash
ASTROVERSE_PORT=5174 ASTROVERSE_BIND=127.0.0.1 docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml up --build -d
python3 tests/browser_sectors_mcp.py --report /tmp/astroverse-http-sectors.json
node --expose-gc tests/benchmark_sector_manager.mjs
docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml down --rmi local
# Проверить обычный стек после stress:
docker compose up --build -d
curl -fsS http://localhost:5173/api/health  # objects=3471
```

Runner (--url, по умолчанию http://localhost:5174) двигает настоящую камеру/controls и использует UI времени, native HTTP,
production PhysicalSectorManager и настоящий WebGL. Fetch не подменяется,
layer.update напрямую не вызывается. Проверяет 48 переходов load/evict/return,
пустую область, точные даты/JD, 409, частичный отказ, несовместимый JD, timeout,
Now/ускорение/реверс при jitter >100 мс, остановку повторов после постоянной
ошибки, renderer identity и GPU-счётчики.
Private React probe читает менеджер/sceneRef, как прежние MCP runners.
Корреляция: X-Astroverse-Client/Selection/Request проходят через nginx JSON
access log и bounded trace provider (4096 записей). Optional onRequest sink
менеджера не хранит историю в production; runner ограничивает свои события 4096.
Сверка в report.reconciliation относится к окну после подключения observer:
каждый fetch либо имеет уникальный request ID в provider, либо завершён cancel
до API. Стартовые/контрольные обращения считаются отдельно. Повтор ID — ошибка.
JSON nginx logs: `docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml logs --no-log-prefix frontend`.
`/api/_test/control` существует только в fixture. Ожидаемые HTTP resource errors
409/422 разрешены; uncaught JS errors запрещены. Screenshot/report временные.

Benchmark отдельно измеряет время native HTTP-менеджера, RSS процесса provider
и RSS клиента Node. Для памяти декодированного компонента wire-строка уже
загружена: после warmup/GC удерживаются 40 payload+PhysicalHierarchy графов,
heap delta делится на 40. Это engine-specific retained heap, без wire-строки,
React/WebGL/сетевого клиента; полный RSS клиента публикуется отдельно.
Сборщика каталога в этом fixture нет: данные генерируются bounded per request.
Расчётный decoded-бюджет менеджера публикуется отдельно от измеренного heap.

`tests/test_position_http.py` поднимает настоящий uvicorn/HTTP с production
positions API и прежним BSP, искусственно задерживает solver, разрывает TCP,
проверяет deadline/ограничение слотов, отсутствие очереди и восстановление.
Для быстрого теста 2 слота / 150 мс; production defaults — 4 / 8 с.
`test_position_work.py` отдельно проверяет удержание слота зависшим native work.
Synthetic sector fixture намеренно сохраняет fault injection 12 с для проверки
клиентского timeout 10 с; это отдельный тестовый provider, без production guard.

## Legacy Playwright smoke

Используется /?scene=legacy и Chrome по пути
/Applications/Google Chrome.app/Contents/MacOS/Google Chrome; playwright install
не нужен. pytest.ini собирает smoke_*.py; fixtures только в browser_smoke/conftest.py.
Маркеры stack3471/stack100k сверяют /api/health и пропускают неподходящие
модули; SMOKE_STRESS не используется. Обычный набор 20 тестов, stress4.

```bash
python3 -m venv /tmp/astroverse-smoke-env
/tmp/astroverse-smoke-env/bin/python -m pip install playwright pytest
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -v
# На 100k:
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -m stack100k -v
# Один тест:
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/smoke_time.py::TestTime::test_date_jumps_pause_resume_and_speed -v
```

SMOKE_HEADED=1 для окна; headless использует SwiftShader (100k~0.5 fps,
не аппаратный GPU). Stress timeout60 с/DOM-click обходят ожидание frame ACK;
обычные navigation45 с/actions10 с. Новый context каждого теста: ru-RU,UTC, 1440×1000;
pageerror собираются до navigation и проверяются в конце. Helpers common.py:
switch_view,wait_row,wait_lod_settled,wait_state,parse_badge_date,served_object_count.
Модули load/views/time/picking/lod/search/binary/stress покрывают соответствующие
UI-сценарии; binary проверяет gzip decoded body, не chunked Content-Length.

Диагностический window.__astroverseSmoke устанавливается только page.evaluate:
ищет актуальный React HostRoot и scene ref через fibers/hooks. Возвращает
view/camera/target/позиции/follow/frame/LOD/resources, экранную проекцию.
Это private React internals, после обновления React probe может требовать правки;
production hooks не добавлены. Probe читает, пользовательские действия идут через UI;
специальные fault/synthetic runners явно подменяют только изолированную страницу.

## Числовые контракты и измерения

Backend test_*.py: catalog/binary/API/source/CLI, sectors/edges/runtime,
streaming/patches, source_registry, positions, physical_hierarchy.
Frontend tests/: legacy и physical UI/hooks/coordinates/hierarchy/layer/resources.
Общие fixtures: binary_catalog.json (Python↔JS), horizons_centers.json (100
реальных векторов с query/frame/origin/TDB/unit), sbdb_field_units.json,
physical_hierarchy_synthetic.json (ручные synthetic координатные эталоны).
Сохранять fixtures и checksum-pinned data/ephemeris/de440s.bsp.

```bash
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_backend build data/catalog_seed.json
docker compose exec -w /app backend python -m tests.benchmark_backend runtime
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_streaming --million
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_registry
node --expose-gc tests/benchmark_hierarchy.mjs
```

benchmark_backend build/runtime разделяет builder и worker /proc RSS;
benchmark_streaming разделяет builder/API/client, генерирует миллион потоком
во временном каталоге и сам удаляет его. benchmark_registry изолирует
sources/positions без полного каталога/nginx/gzip. benchmark_hierarchy измеряет
Node/V8 граф поверх готового frame, не browser/GPU RAM. Первые запросы/медианы
не SLA и не гарантированно холодный filesystem cache.

LOD: `node --expose-gc tests/benchmark_physical_lod.mjs` измеряет retained
heap/ArrayBuffers слоя отдельно от готового входа и полного RSS клиента.
`browser_lod_mcp.py` проверяет L0/L1 picking/refocus и отсутствие HTTP при
движении камеры внутри прежней области. `browser_sectors_mcp.py` дополнительно
проводит 18 zoom-переходов через production manager/HTTP/RAF/WebGL.


CPU/GPU stage: `browser_sectors_mcp.py --report /tmp/astroverse-cpu-sectors.json`
на fixture :5174 измеряет p95 (nearest rank) / max apply, LOD и ready→render,
включая отдельные fullApply/fullLod/fullDisplay для 2048 записей/2016 маркеров.
Apply/tick измеряются вокруг настоящих методов слоя; диагностические подсчёты
не включаются в замер. Display заканчивается возвратом renderer.render,
не GPU fence. Лимиты 16/50 ms, 1/8 ms и 250/1000 ms проверяются assert.
В report: среда, число наблюдений, HTTP durations, provider RSS, пики менеджера,
номинальные GPU bytes, scene geometry/material, listeners window/document/
viewport/canvas и события dispose. Сравнение ресурсов после прогрева и 48
переходов не является доказательством отсутствия всех утечек JS/драйвера.
Runner проверяет численно все 2016 центров и Float32 linear transform.
Запускать итоговые browser-замеры последовательно, без других Chrome stress.
`node --expose-gc tests/benchmark_sector_manager.mjs` теперь также использует
32×64; он меняет fault controls provider, поэтому запускать после браузера.

После основного сценария runner открывает отдельную страницу для admission:
лимит 2048 при resident=2048, Now, терминальная ошибка без повторов (1500 ms),
возврат лимита 4096 и явное восстановление. Никакой fetch mock не используется.
Сводка принятого прогона: [physical_budget_report.json](../docs/physical_budget_report.json).
Временный `--report` содержит также транспортные события/ссылку на screenshot;
постоянный отчёт сохраняет измерения и checkpoints, без временных путей.


Аудит зависимостей перед публикацией: `npm audit` в frontend/;
в одноразовом backend-контейнере установить pip-audit в /tmp и выполнить
`PYTHONPATH=/tmp/audit python -m pip_audit -r backend/requirements.txt`.
Временный scanner не добавлять в production requirements. Результаты и область
аудита — docs/TEST_COVERAGE.md. Runtime/debug *.log и logs/ игнорируются Git;
сохранённый числовой отчёт приёмки не является runtime log.
