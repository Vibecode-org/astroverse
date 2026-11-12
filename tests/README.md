# Проверки Astroverse

Результаты — [TEST_COVERAGE](../docs/TEST_COVERAGE.md), история —
[HISTORY](../docs/HISTORY.md). Сохранять тесты/fixtures/lockfiles/MCP/BSP;
удалять временные reports/screenshots/stress data. Runtime логи игнорируются Git.

## Backend / frontend / CI

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

`-w /app` обязателен: WORKDIR=/app/backend, tests=/app/tests. unittest не
собирает smoke_*.py; контейнер не содержит Playwright/pytest. `.coveragerc`
включает backend/data и branches: общий порог 95%, sectors 100% строк/ветвей.
В frontend/: `npm ci; npm run test:coverage; npm run build`. Vitest/V8 — все
src JS/JSX, HTML coverage/index.html; thresholds statements/lines/functions/
branches = 95/96/96/85 (vitest.config.js). Unit заменяет canvas/WebGLRenderer,
но проверяет Three.js resources; GPU/shaders/fps требуют Chrome. CI push/PR
(.github/workflows/test.yml) проверяет оба coverage/build; browser отдельно.

## Chrome DevTools MCP

Работающий :5173, системный Chrome, chrome-devtools-mcp (проверена 1.12.0).
Python runner запускает MCP stdio + отдельный headless Chrome/SwiftShader;
Playwright/Python-пакеты не нужны. Неверный health/недоступность — ошибка.

```bash
docker compose up --build -d
python3 tests/browser_physical_mcp.py --catalog 3471
python3 tests/browser_lod_mcp.py --catalog 3471
python3 tests/browser_positions_recovery_mcp.py --catalog 3471
python3 tests/browser_latency_mcp.py --catalog 3471
python3 tests/browser_time_bounds_mcp.py --catalog 3471
python3 tests/browser_navigation_mcp.py --report /tmp/astroverse-navigation-real.json
python3 tests/browser_depth_mcp.py --report /tmp/astroverse-depth.json
python3 tests/browser_navigation_regions_mcp.py --report /tmp/astroverse-navigation-regions.json
python3 tests/browser_mcp.py --catalog 3471 --report /tmp/astroverse-legacy.json
```

| Runner | Проверка |
|---|---|
| browser_physical_mcp.py | UTC/центры/zoom/refocus/обзор/время, source pages/ETag/search/cards; growth9/129/1/0 и 20 cross-sector перестановок без роста GPU/recreation |
| browser_lod_mcp.py | L0/L1 picking/refocus/hysteresis, нет HTTP внутри области, drag suppression, Retina pixel ratio=2 |
| browser_positions_recovery_mcp.py | Изолированные revision races/один retry409/repeated conflict/malformed scale, recovery layer/init errors; ожидаемые 409 разрешены, uncaughtJS запрещены |
| browser_latency_mcp.py | Изолированные задержки 200–400 ms, Now/пауза/дата/ускорение/реверс, UTC/лаг/resources |
| browser_time_bounds_mcp.py | UI→HTTP→WebGL: январь 2027/последняя секунда/исключённая граница/Now recovery |
| browser_navigation_mcp.py | Native keyboard 6DoF, поиск/выбор/возврат, origin continuity, manual/Now/forward/reverse, CPU camera/apply/LOD и повторные ресурсы |
| browser_navigation_regions_mcp.py | Все пять resident-центров у Земли; три native wheel/flight/rotate/move/exit/refocus цикла Меркурия после удаления >200 млн км, точные центры и ресурсы |
| browser_depth_mcp.py | readPixels/picking: L0/L1, оба порядка, 1e7…1e12 km; точные полюса, выход/idle/click/native drag |
| browser_mcp.py | Legacy v2/gzip/304, spatial nearby/page/locate/304, views/LOD/search/cards/follow/virtualization/resources |

`--report` сохраняет JSON complete:true и путь screenshot; physical/recovery/
latency report опционален. После переноса измерений временные файлы удалить.

## Synthetic 100k / восстановление

```bash
python3 data/gen_catalog_100k.py
docker compose -f docker-compose.yml -f docker-compose.100k.yml up --build -d
# Те же MCP-команды с --catalog 100000; legacy report — отдельный файл.
# После stress:
docker compose up --build -d
curl -fsS http://localhost:5173/api/health
# Ожидается {"status":"ok","objects":3471}
```

Оба стека используют :5173; objects_100k.json не коммитить. Это synthetic
карточки, не 100k физических положений и не принятый S-100k из ROADMAP.

## Многосекторный HTTP/WebGL fixture

Opt-in Docker project :5174, обычный :5173 не получает synthetic routes/bodies.
Health: synthetic:true, objects:0. 32×64 записи, один unknown/null в секторе,
2016 computed; не NASA/массовая астрометрия.

```bash
ASTROVERSE_PORT=5174 ASTROVERSE_BIND=127.0.0.1 docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml up --build -d
python3 tests/browser_sectors_mcp.py --report /tmp/astroverse-http-sectors.json
node --expose-gc tests/benchmark_sector_manager.mjs
docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml down --rmi local
# Проверить обычный стек после stress:
docker compose up --build -d
curl -fsS http://localhost:5173/api/health  # objects=3471
```

Runner --url (default http://localhost:5174): настоящая камера/controls/UI
времени → native HTTP → production PhysicalSectorManager → WebGL. Нет fetch
mock/direct layer.update. 48 load/evict/empty/return, 18 zoom/hysteresis,
точные UTC/JD/Float64/Float32 transforms всех 2016 центров; даты/revisions/409,
partial failure/mixed JD/timeout, Now/ускорение/реверс с jitter >100 ms,
остановка постоянных ошибок, renderer identity/GPU counters и dispose.
Отдельная страница admission: 2048 resident при лимите 2048 → Now → ошибка,
1500 ms без повторов; лимит 4096/явное действие восстанавливает кадр.

Report fullApply/fullLod/fullDisplay и все переходы: N/p95 nearest rank/max,
среда, HTTP durations/provider RSS/manager peaks, nominal GPU bytes,
geometry/material и listeners window/document/viewport/canvas. Тайминги вокруг
настоящих update/tick без диагностических подсчётов; display после render,
не GPU fence. Бюджеты 16/50 ms, 1/8 ms, 250/1000 ms проверяются assert;
[методика/ограничения](../docs/PHYSICAL_LOD.md), [постоянный JSON](../docs/physical_budget_report.json).
Временный --report также содержит transport events/screenshot, постоянный —
измерения/checkpoints без временных путей. Циклы не доказывают отсутствие любых
утечек. Финальные browser-прогоны последовательны, без другого Chrome stress.

Навигационная приёмка того же HTTP fixture:

```bash
python3 tests/browser_navigation_mcp.py --url http://localhost:5174 --synthetic --report /tmp/astroverse-navigation-synthetic.json
```

Runner запускает временный headless Chrome/SwiftShader с ephemeral debug port,
подключает установленный MCP через browser-url. UI click/fill/press_key идут через
MCP; у press_key нет удержания, поэтому `chrome_hold.mjs` (Node с встроенным
WebSocket) отправляет trusted CDP Input.dispatchKeyEvent в тот же target.
Движение вычисляет production RAF; итоговая позиция камеры не присваивается.
Private React probe только читает состояние/оборачивает методы для замеров;
проекция при rebase использует копию камеры, не меняет сцену. CPU camera/apply/LOD
измеряются раздельно, диагностические подсчёты вне интервала соответствующего
метода. Бюджеты/допуски заранее — [NAVIGATION](../docs/NAVIGATION.md),
постоянный [JSON](../docs/navigation_budget_report.json). Необязательный `--screenshot`
принимает путь внутри системного `tempfile.gettempdir()` (на macOS это обычно
`/var/folders/.../T`, не `/tmp`): собственные path roots MCP ограничивают export.
Временный Chrome/profile закрываются в finally.
Для настоящего hidden-tab сценария runner открывает вторую вкладку, временно
отсоединяет MCP (его session принудительно эмулирует фокус), наблюдает реальный
document.hidden через CDP и подключает MCP обратно. Подмены document.hidden нет;
unit отдельно покрывает blur/visibility/большой dt/отрицательный dt и 30/60/144 Hz.
Функциональный complete и budget_passed в JSON раздельны; нарушение CPU-бюджета
сохраняет отчёт и даёт ненулевой exit code.

Корреляция X-Astroverse-Client/Selection/Request через nginx JSON log и provider
trace (4096), runner events ≤4096, production sink onRequest историю не хранит.
report.reconciliation: окно после observer, уникальный request ID либо cancel
до API; startup/control отдельно, дубликат ID — ошибка. Nginx logs:
`docker compose -p astroverse-sectors-fixture -f docker-compose.yml -f docker-compose.sectors-test.yml logs --no-log-prefix frontend`.
`/api/_test/control` только fixture; ожидаемые HTTP 409/422 разрешены, uncaughtJS нет.

`benchmark_sector_manager.mjs`: 32×64, после браузера (меняет fault controls на
350–550 ms); native HTTP time, provider RSS и весь client Node RSS отдельно.
Wire заранее загружен, warmup/GC, 40 payload+PhysicalHierarchy, heap delta /40:
engine-specific retained component, без wire/React/WebGL/network, не RSS.
Provider генерирует bounded per request, builder нет; decoded estimate отдельно.
`tests/test_position_http.py`: настоящий uvicorn/TCP production positions/BSP,
solver delay/disconnect/deadline/no queue/recovery; 2 slots/150 ms против defaults
4/8s. `test_position_work.py` проверяет удержание native slot до возврата.
Fixture hang=12s испытывает client timeout=10s, отдельный provider без production guard.

## Прямой SBDB import / HTTP acceptance / 100k и 1 млн

Python 3.12+ с backend/requirements.txt, из корня; либо те же команды в
Docker с `-w /app` и **постоянным общим volume** для output SQLite:

```bash
python -m backend.prepare_runtime data/catalog_seed.json data/import.runtime.sqlite
sqlite3 data/import.runtime.sqlite "select value from metadata where key='catalog_revision';"
# Вставить полученный hex без JSON-кавычек:
python -m data.import_sbdb data/import.runtime.sqlite --expected-revision HEX --limit 400
# Опционально --expected-sha256 HEX, --delete-id ID; timeout/retries/max-bytes: --help.
ASTROVERSE_CATALOG_MODE=published ASTROVERSE_SECTOR_PATH=data/import.runtime.sqlite python -m uvicorn backend.app:app

docker compose run --rm --no-deps -w /app backend python -m unittest tests.test_import_sbdb tests.test_import_http -v
docker compose run --rm --no-deps -w /app -v "$PWD/docs:/evidence" backend python -m tests.benchmark_import --output /evidence/import_budget_report.json
```

Пример создаёт отдельный артефакт, seed не заменяет. Docker `run --rm` без
volume теряет результат; env пути сами по себе не монтируют host file.
Fixture `tests/sbdb_fixture.py` генерирует SBDB JSON по строке через настоящий
TCP HTTP, без готового массива: count/fields/signature, обрыв, повреждённые поля,
дубликаты, timeout/503/400/redirect/Content-Length. `test_import_http` запускает
production uvicorn без исходного JSON и проверяет health/search/card/page/304/409
и смену ревизии работающего API. Есть SIGKILL/restart, concurrent writers,
expected_revision, старый читатель, pin, update/explicit delete, parent/cycles.

Benchmark: отдельный importer process на размер, отдельный fixture process;
Sun + N synthetic астероидов, один неделимый solar сектор. ru_maxrss импортера
в Linux включает SQLite; не сумма RSS fixture/API. Таймеры разделяют HTTP/raw
stage, merge/normalization, повторную проверку/ingest builder, graph/spatial/index,
legacy v1/v2, VACUUM, validation и fsync/rename. Индексация не измерена как
O(изменений); input source не записывается полным JSON. После замера — настоящий
production HTTP/API против опубликованной БД, затем временный каталог удаляется.

Бюджеты заданы **до stress**: RSS ≤384 MiB; разница 1m−100k ≤64 MiB; время
≤300/1800 s; peak disk ≤1/10 GiB. Диск: каждые 20 ms stat named files +
/proc/PID/fd (включая unlinked SQLite/VACUUM/legacy spools), blocks×512,
каждый inode один раз; named staging отдельно. Это sampled process footprint,
не максимум всего Docker filesystem; короткий пик может быть пропущен.
Baseline — маленькая активная БД; обновление уже миллионной БД требует места
ещё и под прежнюю версию. Две точки не доказывают асимптотику RSS для любого N.
Среда/результат — [report](../docs/import_budget_report.json), сводка — TEST_COVERAGE.
Обычный compose после stress восстановить и проверить health=3471.

## Legacy Playwright smoke

/?scene=legacy, системный /Applications/Google Chrome.app/Contents/MacOS/Google Chrome;
playwright install не нужен. pytest.ini собирает smoke_*.py, fixtures только
browser_smoke/conftest.py. stack3471/stack100k проверяют health и skip другой стек;
SMOKE_STRESS не используется. Обычный набор 20, stress4.

```bash
python3 -m venv /tmp/astroverse-smoke-env
/tmp/astroverse-smoke-env/bin/python -m pip install playwright pytest
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -v
# На 100k:
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -m stack100k -v
# Один тест:
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/smoke_time.py::TestTime::test_date_jumps_pause_resume_and_speed -v
```

SMOKE_HEADED=1 — окно; headless SwiftShader ~0.5 fps/100k, не аппаратный GPU.
Stress timeout60s/DOM-click обходят frame ACK; обычные navigation45s/actions10s.
Context ru-RU/UTC/1440×1000, pageerror до navigation/проверка в конце.
common.py helpers: switch_view/wait_row/wait_lod_settled/wait_state/
parse_badge_date/served_object_count. Модули load/views/time/picking/lod/search/
binary/stress; gzip проверяется encoding+decoded body, не chunked Content-Length.
Probe window.__astroverseSmoke ставится только page.evaluate, ищет HostRoot/
sceneRef через fibers/hooks; возвращает view/camera/target/positions/follow/
frame/LOD/resources/projection. Private React internals могут потребовать правки
после upgrade, production hooks нет. Probe читает, действия через UI;
fault/synthetic подменяют только изолированную страницу.

## Числовые контракты / benchmarks / аудит

Backend test_*.py: catalog/binary/API/source/CLI/sectors/edges/runtime/streaming/
patches/registry/positions/hierarchy. Frontend tests/: legacy/physical UI,
hooks/coordinates/hierarchy/layer/resources. Fixtures: binary_catalog.json
(Python↔JS), horizons_centers.json (100 реальных query/frame/origin/TDB/unit),
sbdb_field_units.json, physical_hierarchy_synthetic.json (ручные эталоны).

```bash
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_backend build data/catalog_seed.json
docker compose exec -w /app backend python -m tests.benchmark_backend runtime
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_streaming --million
docker compose run --rm --no-deps -w /app backend python -m tests.benchmark_registry
node --expose-gc tests/benchmark_hierarchy.mjs
```

benchmark_backend разделяет builder/worker /proc RSS; benchmark_streaming —
builder/API/client, генерирует миллион потоком во временном каталоге и удаляет
его; benchmark_registry — sources/positions без каталога/nginx/gzip;
benchmark_hierarchy — Node/V8 поверх готового frame, не browser/GPU RAM.
`node --expose-gc tests/benchmark_physical_lod.mjs`: retained heap/ArrayBuffers
слоя поверх входа отдельно от RSS. Первые запросы/медианы не SLA/не гарантия cold FS cache.
Аудит: npm audit в frontend; одноразовый backend pip-audit в /tmp/audit,
`PYTHONPATH=/tmp/audit python -m pip_audit -r backend/requirements.txt`.
Scanner не добавлять в production requirements; область/результаты в TEST_COVERAGE.

## Synthetic physical S-100k (SQLite, opt-in)

```bash
ASTROVERSE_PORT=5174 ASTROVERSE_BIND=127.0.0.1 docker compose -p astroverse-s100k-fixture -f docker-compose.yml -f docker-compose.s100k-test.yml up --build -d
# Открыть http://localhost:5174/ — профиль сам открывает 100000 точек.
python3 tests/browser_s100k_mcp.py --seconds 30 --report /tmp/astroverse-s100k-software.json
# Отдельно, без сборок/тестов одновременно; только настоящий GPU принимает fps:
python3 tests/browser_s100k_mcp.py --hardware --seconds 30 --report /tmp/astroverse-s100k-hardware.json
docker compose -p astroverse-s100k-fixture -f docker-compose.yml -f docker-compose.s100k-test.yml down --rmi local
docker compose up --build -d
curl -fsS http://localhost:5173/api/health  # objects=3471
```

Профиль и ограничения: [S100K](../docs/S100K.md), постоянный машинный отчёт:
[s100k_report.json](../docs/s100k_report.json). SQLite живёт в /tmp контейнера;
полный objects.json не нужен. Chrome `--hardware` убирает software-флаги;
проверять фактический WebGL renderer, само имя флага не доказывает GPU.
Runner использует отдельный Chrome 1920×1167 (viewport/framebuffer 1920×1080,
DPR1), MCP native UI и CDP trusted held keys/pixel click через chrome_hold.mjs.
Никакого присваивания камеры/кадра. Полные read-only probes вне steady sample.
Временный screenshot пишется в системный tempfile.gettempdir()/astroverse-s100k.png;
после просмотра удалить. Итог complete — функциональное выполнение runner;
hardware_criterion_passed и весь продуктовый рубеж принимаются отдельно.

CPU baseline текущего обычного слоя (4096, Node, без WebGL):
`node tests/benchmark_physical_baseline.mjs`. Первоначальный вывод до изменений
сохранён отдельно в s100k_report.json; повторный запуск измеряет текущий код.
Отдельный `node tests/s100k_overlap.mjs` считает номинальные пересечения 5px
маркеров в начальном ракурсе, не измеряет GPU-окклюзию или производительность.

Численная проверка непустого rebase отдельно от benchmark:
`python3 tests/browser_s100k_mcp.py --rebase-only --report /tmp/astroverse-s100k-rebase.json`.
Trusted wheel OrbitControls отдаляет камеру, затем native flight запускает
rebase при всех 100000 загруженных центрах. Сверяются биты всех центров и 16
экранных проекций; полный read-only inspect выполняется вне FPS-замера.

Чистые динамические окна S-100k (без builds/coverage/других browser tests
одновременно):
```bash
python3 tests/browser_s100k_dynamic_mcp.py --hardware --seconds 10 --report /tmp/astroverse-s100k-dynamic.json
```
Runner использует обычный :5174 HTTP/UI/manager/WebGL; trusted CDP input через
chrome_hold.mjs. 3 s warmup steady, 1 s перед каждым последующим окном;
отдельные steady, 20 picking clicks, yaw/pitch/roll/W, rebase/eviction, Now,
ускорение, реверс, три search/refocus/flight/return цикла. Параметр seconds —
добавочная длительность наблюдения после действий, не длительность всего окна.
Все полные SUMMARY/identity/numeric/frustum scans выполняются после закрытия
окна; внутри — ограниченные счётчики и максимум 20000 samples/metric.
CPU-инструментирование включает performance.now/array push; отдельный micro-loop
оценивает их нижнюю стоимость, не весь overhead callbacks/GC. Latency manager
load — elapsed admitted desired→accepted; ready→display включает staging и
ожидание RAF. Ожидание coalescing до admission отдельно пока не измеряется.
CPU render submission включает возможную driver upload работу; GPU fence нет.
Данные SwiftShader и Metal нельзя напрямую сравнивать как ускорение кода.
HTTP отдельно записывается Resource Timing observer: responseEnd−startTime,
без JSON decode. Decode/validation/merge/preparation/commit CPU — отдельные
синхронные spans. `python3 tests/report_s100k_dynamic.py` заново строит оценку
сохранённого результата по действующим порогам (frame p95≤16.8ms согласован пользователем2026-11-12), без запуска benchmark.


Расширенный стресс (отдельно от builds/coverage/других Chrome runners):
```bash
python3 tests/browser_s100k_dynamic_mcp.py --hardware --seconds 15 --cycles 12 --report /tmp/astroverse-s100k-stress.json
```
Каждый повторный цикл имеет отдельное окно; после него вне замера проверяются
все identities/центры, renderer, geometry/textures/listeners и бюджеты manager.
Browser errors/unhandled rejections завершают runner ошибкой. `complete` означает
функциональное завершение; оценка распределений по бюджетам выполняется отдельно.

Runner сначала проверяет synthetic health100000; отсутствие fixture завершается
явной ошибкой до запуска Chrome. При ошибке сохраняются complete=false и error,
а завершённые окна не теряются. Неполный отчёт не является PASS.
