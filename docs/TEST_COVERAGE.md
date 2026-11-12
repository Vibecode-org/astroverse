# Проверки и измерения

Сводка актуальна на **2026-11-12**. Это сохранённые результаты завершённых
прогонов, не утверждение о запуске тестов при каждом редактировании документа.
Команды — [tests/README.md](../tests/README.md), контракты —
[COORDINATES](COORDINATES.md), [SECTORS](SECTORS.md), [SOURCES](SOURCES.md),
[HIERARCHY](HIERARCHY.md). Промежуточные счётчики тестов заменены последним
результатом; уникальные измерения ниже сохраняют дату/контекст прогона.

## Последние проверки

| Проверка | Результат |
|---|---|
| Полный backend, Docker | 242 теста, OK; 2026-11-12 |
| Backend coverage с ветвями, 2026-11-12 | 98.38%, 2457 statements / 1133 branches |
| Индекс data/sectors.py | 197/197 statements, 113/113 branches — 100% |
| Positions API | 131/131 statements, 74/74 branches — 100% |
| Frontend, 2026-11-12 | 216 тестов, пороги пройдены |
| V8 statements / lines / branches / functions | 97.86% / 98.97% / 91.89% / 97.83% |
| Production Vite/Docker build | Проходит; известный общий chunk >500 kB |
| Независимая астрометрия | Все 100 Horizons-векторов пяти тел проходят |

CI настроен на backend ≥95%, индекс 100%, frontend 95/96/85/96
(statements/lines/branches/functions) и build. Удалённый результат CI проверяется
отдельно. Общий backend/frontend не имеет 100% всех ветвей; исключения ради
процента не добавлялись. Unit WebGL/canvas заменены; GPU проверяется Chrome.
Покрытие не доказывает отсутствие всех багов и не заменяет астрометрию.

## Synthetic physical S-100k, 2026-11-12

[Профиль/бюджеты/ограничения](S100K.md), [постоянный JSON](s100k_report.json).
100×1000 SQLite → HTTP → production manager → тот же Points/WebGLRenderer.
При обычном открытии fixture: **catalog/resident/computed/submitted/in-frustum =
100000/100000/100000/100000/100000**. Submitted проверен по настоящему
`renderer.info.render.points`; draw calls=1. Все ID/канонические центры сверены;
намеренное точное совпадение пары, 1 совпадение округлённых пиксельных центров.
Номинальные 5px диски: все 100000 имеют пересечение хотя бы с одним соседом;
1126913 пар по отдельному offline-проецированию. Это не GPU raster occlusion;
число неперекрывающихся дисков не равно 100000.
Нет policy-hidden/culling ради счётчика. L0/L1, без L2/физических радиусов.

Chrome 157, macOS 26.3 arm64, Apple M1 Pro/ANGLE Metal, 10 reported CPU cores,
1920×1080 framebuffer, DPR1. Прогрев 3s, steady 30s, без параллельных сборок/
тестов. SwiftShader прогнан отдельно (20s steady), только функциональный.
Подробные p50/p95/p99/max, доли кадров ≤16.667ms, пики manager/RAM/GPU-атрибутов
и различия steady/scenario/CPU/Promise wall time — JSON, не средний fps.
Аппаратный 60+ fps и весь S-100k **остаются открыты**: заранее заданный p95
16.667ms не пройден; headless RAF округляет интервалы, сценарные паузы включают
read-only probes всего набора. Чистый dynamic benchmark ещё нужен.

| Метрика | N | p95 / p99 / max, ms |
|---|---:|---:|
| Frame-time steady | 1807 | 16.70 / 16.80 / 16.80 |
| CPU camera steady | 1814 | 0.20 / 0.30 / 1.30 |
| CPU LOD steady | 1814 | 0.30 / 0.60 / 3.30 |
| Sync apply / eviction | 43 | 0.20 / 0.20 / 0.20 |
| Staged CPU commit | 25 | 0.80 / 0.80 / 0.80 |
| Picking | 4 | 3.10 / 3.10 / 3.10 |

Первый опубликованный WebGL-набор наблюдён через 2.308s
после fresh navigation в уже работающий fixture. Steady: 0
пауз >50ms; доля интервалов ≤16.667ms — 37.80%
(буквальное сравнение округлённых RAF timestamps). Макс. порция подготовки
7.50ms при целевом 4 / max 16; preparation wall p95
1120.10ms включает yield, не является long task.
Сценарные паузы: 7 >50ms, max 266.80ms,
включая полные диагностические чтения; этот динамический критерий не закрыт.

Поиск/карточка/refocus: начало/конец, границы секторов, оба совпавших центра.
Три native yaw/pitch/roll/движение/rebase/выгрузка/возврат: неизменные binary64
центры, отдельный непустой rebase всех 100000: 16 экранных проб, max 3e-14 CSS px (порог 0.05), тот же renderer,
1 geometry/0 textures и стабильные 28 учтённых listeners после прогрева.
Manual date/Now/ускорение/реверс с прогрессом отображаемого UTC и renderer backpressure, partial failure без fallback, revision 409 с
атомарным retry. Unit дополнительно проверяет 100k identity/linear transform,
отмену подготовки/dispose/reuse, два временных набора и partial failure manager.
GPU-атрибуты 3670016 Б (131072 capacity), staging CPU ещё столько же;
manager cap 200000 строк/64MiB wire/512MiB decoded estimate/4 worker. Heap без
forced GC и provider RSS сохранены; driver RAM и полное отсутствие утечек
не доказаны. GPU-данные не используются как источник физических центров.

Обычный стек: physical 13/13, LOD 5/5, recovery 7/7, UTC 4/4, navigation 7/7,
depth 2/2 (включая 12 pixel/picking кейсов), legacy 10/10 и latency прошли.
Все 100 Horizons: max 0.002420538 km при прежнем регрессионном допуске 1 km.
Source/пять DE440s центров/BSP/даты не изменены; 3.7-A сохранён, 3.7-B не включён.

## Дебаг глубины, picking и pole handoff, 2026-11-11

Базовые unit suites проходили до исправлений; canvas/controls mocks скрывали
ошибки. [Постоянный отчёт](debug_report_2026_11_11.json), детали — HISTORY.
Реальный WebGL `readPixels` после исправления даёт ближний красный маркер
`[255,0,0,255]` в **12/12** случаях: L0/L1, оба порядка, расстояния 1e7/1e9/1e12 km.
Picking выбирает тот же передний ID; исходные центры неизменны, GL error=0.
До исправления дальний синий перекрывал ближний при включённом renderer log depth.

Настоящий OrbitControls до исправления смещал camera eye на ~1.2 km при выходе
из полёта у мировых Y-полюсов. После исправления оба полюса сохраняют eye и
quaternion без изменения (измеренная ошибка **0**; допуски 1e-6 km / 1e-12
компоненты quaternion). Idle и клик без движения не будят камеру; native drag
восстанавливает управление. Unit дополнительно проверяет 100 idle updates,
start без change и явный autoRotate, без mock для OrbitControls.

После исправлений Chrome MCP: depth/pole **2/2 группы**, navigation **7/7**,
synthetic HTTP **8/8**, physical **13/13**, LOD **5/5**, recovery **7/7**;
latency 20/20 nonempty, 3 distinct frames, forward/reverse по 25 samples и
6 distinct frames, pause/manual exact. Итоговые camera/apply/LOD бюджеты обеих
navigation-сцен пройдены; распределения в JSON. Проверены 5 и 2016 центров,
неизменные renderer/resources/listeners. Все 100 Horizons-векторов проходят.
SwiftShader функциональный; аппаратные fps и S-100k не подтверждены.

## Навигация: ограниченный 8.1 / минимум 8.2 и 8.6, 2026-11-10

[Контракт, заранее объявленные допуски/бюджеты](NAVIGATION.md),
[машинный отчёт](navigation_budget_report.json), [команды](../tests/README.md).
Chrome MCP + trusted CDP keyboard/mouse → production RAF/manager → HTTP/WebGL:
обычная сцена **7/7**, synthetic HTTP **8/8**. Итоговые прогоны последовательны,
без параллельных сборок: macOS 26.3 arm64, Chrome 157, SwiftShader, 10 logical
cores, viewport 1440×913, DPR 1. Не аппаратные GPU fps, нет CPU isolation.

| CPU работа | Обычная сцена: N; mean/p95/max, ms | Synthetic: N; mean/p95/max, ms | Бюджет p95/max, ms |
|---|---:|---:|---:|
| Camera update | 727; 0.040/0.10/6.60 | 1068; 0.036/0.10/4.50 | 1/8 |
| Apply позиций | 154; 0.125/0.40/2.60 | 79; 0.935/4.90/32.20 | 16/50 |
| LOD tick | 727; 0.010/0.10/2.50 | 1068; 0.013/0.10/2.50 | 1/8 |

Все итоговые бюджеты пройдены; это смеси активных/пустых/idle кадров и обоих
controls, не p95 только полного набора или GPU fence. Camera исключает apply;
apply включает перепроекцию при rebase. Предварительное превышение camera max
9.3 ms сохранено в JSON/истории, порог не повышался; причинность и hard realtime
не доказаны. Методику/исправления runner и hot path см. HISTORY.

Проверены локальные оси после yaw/pitch/roll, native drag без выбора/движения
OrbitControls, поиск → выбор/карточка без телепортации → явный refocus/follow.
Пауза, ручная дата, Now, ±86400x сохраняют свободную камеру и заданную скорость.
Настоящее скрытие вкладки во время удержания W сбрасывает команду, возвращение
не отрабатывает пропущенный dt. Unit дополнительно проверяет 30/60/144 Hz,
большой/отрицательный dt, blur/cancel/editable/modifiers/key repeat и disposal.

Численно проверены 5 и 2016 физических центров/линейных GPU-преобразований;
unknown/null не рисуются. Ошибка направления local forward ≤1.34e-13;
смена origin: ≤0.000030 CSS px на 5 и ≤0.000017 CSS px на 2016 общих видимых
центрах (бюджет 0.05 px). Physical eye до/после origin совпал в пределах 1e-6 km.
Unit сохраняет исходные центры побитово при движении/поворотах и rebase,
проверяет sub-ULP offsets при начале 1e18 km. Все 100 Horizons-векторов сохранены
и проходят независимую астрометрию с прежним максимумом 0.002420538 km.

На HTTP fixture полёт клавишами загружает/вытесняет области, возвращается к
выбранному телу; ошибка сектора атомарно очищает слой, refocus восстанавливает.
По 12 циклов в каждой сцене: прежний renderer, 1 canvas/geometry, 0 textures,
28 учтённых listeners без роста; это не доказательство отсутствия любых утечек.
Flight screenshot просмотрен. Пределы 4096 слотов/2048 fixture resident сохранены;
S-100k, полная Фаза 8, поверхности и аппаратные 60+ fps остаются открыты.

Полная прежняя HTTP/WebGL регрессия после навигации: **10/10 + admission**,
48 переходов без роста ресурсов, 28 listeners, 1 geometry/material/draw call,
0 textures. Полный набор: apply p95/max **4.8/4.9 ms** (20), LOD **0.1/0.1 ms**
(697), ready→render **50.4/50.4 ms** (18); все бюджеты пройдены.
Now/ускорение/реверс с jitter, exact pause/date, cancellation/409/partial error/
mixed JD/10s timeout и терминальная ошибка clock-контекста сохраняются.
Пики: 4096 записей, 1918064 Б serialized, 16663424 Б decoded estimate, 4 workers;
848 captured запросов, 845 provider, 3 cancel до provider, 0 duplicate ID.
Отдельная admission-проверка снова остановилась при лимите 2048 и восстановила
2048 resident после явного действия/лимита 4096. Данные в том же JSON.

Обычный 3471 стек: physical **13/13**, LOD **5/5**, recovery **7/7**, UTC bounds
**4/4**, legacy **10/10**; latency **20/20** steady nonempty, 3 distinct frames,
по 25 samples в каждом направлении (5/6 distinct frames), pause/manual exact.
Обычный physical screenshot просмотрен. Fixture/project images удалены;
обычный compose без override восстановлен, `/api/health`: **3471**.

## Прямой import: 3.7-A / минимум 7.1/7.2, 2026-11-10

SBDB HTTP → SQLite raw stage → нормализация/merge → существующий streaming
builder → integrity/references/R-tree/semantic SHA-256 → atomic revision.
[Контракт/лимиты](SECTORS.md#прямой-sbdb-import-ограниченный-37-a),
[методика и команды](../tests/README.md#прямой-sbdb-import--http-acceptance--100k-и-1-млн),
[постоянный JSON](import_budget_report.json). Full source/list/objects.json в RAM нет.

Реальные TCP fixtures: repeat/pin/no timestamp-only revision, update/explicit
owned delete/omission preserves, legacy IDs/visual overrides, ambiguous identity,
duplicates/bad fields/parent/cycle, malformed/truncated/count mismatch/Content-Length,
redirect/timeout/ограниченные retries. Проверены два writers/expected_revision,
старый reader, ошибка validate/rename, повреждение готового кандидата и SIGKILL
→ cleanup/restart с новым входом. Production uvicorn без JSON: health, search,
карточка, sector pagination, ETag 304, revision 409, смена версии без рестарта.

Live JPL limit=3/API 1.0 прошёл; query/hash — [HISTORY](HISTORY.md#прямой-sbdb-import-37-a-2026-11-10).
Это проверка адаптера/формата, не массовая загрузка или подтверждение positions.

Бюджеты до stress: RSS ≤384 MiB, прирост ≤64 MiB, время ≤300/1800 s,
peak disk ≤1/10 GiB. Все пройдены; [точные значения/среда](import_budget_report.json).
Linux Docker aarch64, Python 3.12.16, SQLite 3.46.1, 10 reported CPU;
без CPU isolation, параллельно шли backend/browser проверки. Fixture/API отдельно.

| Величина | 100k | 1 млн |
|---|---:|---:|
| Всего, s | 12.29 | 130.19 |
| Peak RSS, MiB | 55.76 | 55.69 |
| БД, MiB | 118.80 | 1191.80 |
| Named staging peak, MiB | 422.89 | 4310.65 |
| Весь sampled disk peak, MiB | 534.02 | 5494.79 |
| HTTP/raw stage, s | 0.77 | 8.10 |
| Merge/normalization, s | 2.77 | 30.57 |
| Builder ingest/validation, s | 2.59 | 26.41 |
| Graph/spatial/index, s | 2.48 | 26.38 |
| Legacy v1/v2, s | 2.16 | 22.50 |
| VACUUM, s | 0.70 | 8.17 |
| Final integrity/hash validation, s | 0.41 | 4.49 |
| Fsync/rename, ms | 0.92 | 0.25 |

Peak RSS: ru_maxrss; /proc VmHWM checkpoints отличаются <0.3 MiB и также
стабильны (~55.9 MiB). После merge ~38.4 MiB, после builder ~55.9 MiB на обоих N;
в Python нет контейнера размера N, SQLite caches ограничены. Измеренный RSS
не вырос от 100k до миллиона; две точки не доказывают bounded RSS любого входа.
Legacy v1: 2600046/26000046 Б; v2: 10889148/109889148 Б. Peak disk sampled
каждые 20 ms, включая открытые unlinked spools, каждый inode один раз; короткий
пик может быть пропущен. Один solar parent/сектор, baseline Sun; при замене уже
миллионной БД нужно дополнительно место старой версии. Это не stress всех форм
пространственного графа. Полный SQL merge/граф/индексы/VACUUM/semantic validation/
legacy остаются O(N), B-tree/sort могут добавлять log N; 3.7-B, другие adapters
и массовый physical streaming открыты.
Старый online builder совместимости остаётся списочным.

MCP обычного 3471: physical **13/13**, legacy **10/10**, LOD **5/5**, recovery
**7/7**, UTC bounds **4/4**; latency: 20/20 steady nonempty, 4 distinct frames,
25 samples × forward/reverse, pause/manual date exact. Physical screenshot просмотрен
вместе с числовыми проверками Float64/linear transform/дат; 100 Horizons vectors
проходят, max 0.002420538 km. SwiftShader не аппаратные 60 fps и не S-100k.
Обычный compose без override восстановлен после stress; `/api/health`: 3471 объект.

## Текущая приёмка 3.4/3.8: 32×64, 2026-11-10

Настоящий HTTP → production manager → WebGL: 10 основных сценариев и отдельная
регрессия admission. 2048 resident записей, 2016 маркеров и 32 unknown/null;
production остаётся на пяти DE440s центрах. Это не приёмка S-100k из ROADMAP.
[JSON с измерениями/checkpoints](physical_budget_report.json), политика/бюджеты —
[PHYSICAL_LOD](PHYSICAL_LOD.md), команды — [tests/README](../tests/README.md).

Chrome 156/ANGLE Vulkan **SwiftShader**, macOS 26.3 arm64, 10 reported logical
cores, 1440×1000/DPR 1; прогон последовательный. P95 nearest rank; apply включает
hierarchy decode/slots/linear transform, LOD — tick ≤128 центров. Ready начинается
после manager validate/merge, display заканчивается возвратом renderer.render:
CPU submission, не GPU fence/вывод на монитор/производительность аппаратного GPU.

| Величина | N | p95 / max, ms | Бюджет p95 / max |
|---|---:|---:|---:|
| Apply полного набора | 21 | 5.70 / 6.20 | 16 / 50 |
| LOD полного набора | 747 | 0.10 / 0.20 | 1 / 8 |
| Ready→render полного набора | 19 | 48.30 / 48.30 | 250 / 1000 |
| Apply всех переходов | 136 | 4.90 / 6.20 | 16 / 50 |
| LOD всех переходов | 3847 | 0.10 / 0.20 | 1 / 8 |
| Ready→render всех переходов | 71 | 48.30 / 523.00 | 250 / 1000 |

Синхронное применение проходит; staged GPU commit не потребовался. На этапе
до аудита frontend 196/196; актуальные 197/197 — в сводке выше.
Now/86400x/−86400x: по 100/100 непустых отсчётов, 3 разных UTC каждого режима;
100 ms interval, первые 60 samples отброшены. Проверены даты/revisions/409,
partial failure, несовместимый JD, отмена, реальный timeout 10s и восстановление.
Однонаборный лимит: пик ≤2048, active/resident=0 после ошибки, 1500 ms без повторов;
после лимита 4096 и явного Now восстановлены 2048 resident.

Пики: 4096 записей, 1922096 Б serialized, 16695680 Б decoded estimate,
4 active / 32 queue. Старые 16 MiB оставляли ~80 KiB запаса; текущий предел 32 MiB.
Provider RSS 69112 KiB, builder отсутствует. HTTP включает read/decode/validate,
provider — injected sleeps; N/p95/max в JSON, максимумы включают 10s timeout/12s hang.
Корреляция: 849 попыток, 847 provider, 2 cancel до него, 0 дублей.

Численно проверены все 2016 Float64 центров/Float32 преобразований. На каждом из
48 load/evict/return после прогрева: тот же renderer, 1 geometry/material/canvas/
draw call, 0 textures, 17 учтённых listeners window/document/viewport/canvas,
capacity=2048, slots=63 или 0 в малой/пустой области и 2016 в полном наборе.
Атрибуты 57344 Б (nominal cap 114688 Б), не driver RAM. Dispose дал по одному
событию geometry/material и renderer geometries=0; screenshot просмотрен.

Отдельный Node v26.13.0 --expose-gc: retained payload+Hierarchy 916786 Б/набор
(batch 40 после warmup/GC, wire предзагружен), весь client RSS
112974016→142410496 Б, provider RSS 69692→70092 KiB. Heap delta не browser RSS
и не decoded estimate. Эти циклы/цели событий не доказывают отсутствие любых
JS/driver утечек, context loss и устойчивость произвольного устройства.

## Предыдущий аудит зависимостей

После security-обновления: обычный 3471 стек physical 13/13, LOD 5/5,
recovery 7/7, UTC bounds 4/4. Исторические результаты 100k/legacy/latency,
изменения LOD-теста и численные эксперименты — [HISTORY](HISTORY.md).
32×64 не повторно измерялись после аудита; сохранён отдельный исходный прогон.

Vite 6.4.4→6.4.6, FastAPI 0.115.12→0.162.3, Starlette 0.46.2→1.10.0
(явный pin), certifi 2025.4.26→2026.10.23; npm audit/pip-audit по requirements
дали 0 известных уязвимостей. Исправлены stale pendingDisplay acknowledgement
после неудачного apply и ложная подпись registry count как вычисленных позиций.
Область аудита, advisories, воспроизведённая регрессия и log cleanup — HISTORY.
Это не OS-image scan/полный пентест; Python transitive зависимости не полностью
locked. Остались chunk >500 kB и deprecated httpx TestClient/websockets adapter.
Обычный стек восстановлен, health=3471; временные артефакты удалены,
fixtures/lockfiles/MCP/BSP и предсуществовавшие dependencies/coverage сохранены.

## Числовые и контрактные регрессии

- DE440s ↔ независимый Horizons DE441: ICRF/SSB/geometric/km/TDB, 20 дат на
  Sun 10 / Earth 399 / Moon 301 / Mercury 199 / Venus 299. Максимум **0.002420538 km**
  (Луна), Mercury **0.000002765 km**, Venus **0.000002098 km**; допуск **1 km**.
  Это регрессия на выбранных датах, не абсолютная неопределённость/ошибка
  всего интервала. accuracy=null; BSP/100 числовых эталонов сохранены.
- UTC↔TDB, timezone/leap seconds, границы интервала, unknown/null,
  неподдержанная дата/кернел, возврат даты без дрейфа. Барицентр не центр тела.
- Все 100 векторов проходят клиентские преобразования разных опор с ошибкой
  арифметики <1e-6 km на этих входах. Это roundoff, не точность эфемериды.
  Synthetic fixture проверяет разные ненулевые начала/секторы/системы,
  переназначение адресов, направления/расстояния, null, дубликаты/родителей,
  metadata/revision/time/caps. Локальные sub-ULP offsets при общем начале 1e18 km
  сохраняются, потерянная исходным double информация не восстанавливается.
- Registry: неоднозначные identity/дубликаты, center/barycenter, SHA-256,
  размеры записей/ответов, интервалы/типы, bounded pages/search, revision/ETag,
  304/409/413/422. Synthetic provider 9 объектов не требует правки сцены/решателя;
  129 в одном HTTP-секторе даёт 413, не усечение. Новых реальных тел не добавлено.
- Snapshot/index: R-tree против независимого перебора 100 запросов, октанты,
  float32/64 границы, цепь parent 1100, unknown frames/эпохи, oversized families,
  404/409/413/422/503, byte LRU, split/merge/движение семейства, independent ETag.
  Лимиты проверяются до условного 304; следующая большая карточка не блокирует
  текущую страницу. Ошибки build/commit не заменяют прежний артефакт.
- Runtime/patches: snapshot pin/atomic rename/старые транзакции,
  expected_revision, parent closure, reuse листьев, limits, startup freshness;
  legacy JSON/v1/v2 побайтово сохраняют wire/order, кириллицу/фильтры/parents.
  Python encoder↔JS reader защищён общим fixture; corrupt offsets/parents/UTF-8
  отвергаются. Проекция снимков проверена ERFA t_s2c, не положением реального тела.
- Проверяются отказы/retry/backoff источников/CLI, offline fallback, CORS,
  rate limiting, сохранение старого каталога и null. Legacy frontend:
  LOD/пикинг/dispose/детерминизм, время/follow/виды, загрузка/ошибки/виртуализация.

После fixture обычный compose без override восстановлен; финальный `/api/health`:3471 объект.

## Регрессии областей камеры, 2026-11-12

При наблюдении Земли все пять computed-центров resident-сектора участвуют в
отрисовке; дополнительное дистанционное скрытие L0 удалено в обоих путях
применения кадров. Решение об освобождении секторов остаётся у manager.
Вход в полёт сохраняет охват отдалённой orbit-камеры; повторный выход/zoom/вход
тоже сохраняет охват. Unit проверяет rebase, null/loading и повторное увеличение
области, не пересоздавая renderer.

Chrome MCP/SwiftShader: три цикла Меркурия после native wheel-отдаления до
~220 млн км, yaw/pitch/roll, W, выход/повторный вход/refocus. Переход камеры
0 км при допуске 1e-6 км; все пять Float64-центров равны HTTP-векторам, ресурсы
и listeners стабильны. [Машинный отчёт](navigation_regions_report.json),
runner `tests/browser_navigation_regions_mcp.py`. Это функциональная проверка;
замеры S-100k в прежнем отчёте сохраняют дату и хеши исходников своего прогона.

## S-100k bounded update / clean dynamic windows, 2026-11-12

Backend242/242, coverage98.38%, sectors100%; все 100 Horizons-векторов сохранены,
max0.002420538km. Frontend222/222, coverage statements97.83/branches91.41/
functions98.22/lines99.09%; production Docker build прошёл с прежним chunk warning.
Новые риски: cancellation global merge/flat decode, освобождение staging и
повторное использование worker/slots, atomic publication, origin mid-staging,
малый offset при общей опоре 1e18km и hidden-tab scheduler drain.

Чистые динамические 8 окон — [S100K](S100K.md), итоговые метрики/assessment,
бюджеты и исходные hash — [s100k_report](s100k_report.json#dynamic_update_stage).
CPU/подготовка/commit/picking/cold/draw/memory проходят; frame p95 остаётся
FAIL16.7–16.8>16.667ms, p99 проходит, пауз>50ms ноль. Это Metal headless,
не измерение вывода монитора и не закрытие всего рубежа S-100k.
Функциональные 100k identities/центры/date/Now/reverse/failure/revision/cycles —
[s100k_update_functional](s100k_update_functional.json); непустой 100k rebase —
[s100k_update_rebase](s100k_update_rebase.json), битовые центры сохранены.

Обычный стек после нового кода: physical13/13, recovery7/7; LOD, UTC bounds,
latency, depth/poles, legacy и обязательный navigation_regions завершились с
exit0. [Новые machine results](s100k_update_regressions.json),
[Земля/Меркурий](navigation_regions_update_report.json): пять центров Земли,
три удаления/полёта Меркурия >200млнkm, скачок0km, стабильные ресурсы.
Navigation прошёл7 функциональных сценариев/12циклов, но CPU budget **FAIL**:
camera max11ms>8ms, p95 0.1ms; apply/LOD проходят. Причина outlier не установлена,
повтором до PASS результат не заменялся. [Evidence](navigation_update_budget_report.json).
Обычный compose без override восстановлен; health3471. Временные task artifacts
удалены; исходники/fixtures/BSP/lockfiles/предыдущие незакоммиченные работы сохранены.


## Повторная стресс-приёмка перед публикацией,2026-11-12

По явному решению пользователя текущий frame p95≤16.8ms. Старые16.667ms и FAIL
сохранены в истории/raw reports. Новая [стресс-приёмка](s100k_stress_report.json):
12 циклов,19 окон,11475 RAF samples/191.59s; p95/p99/max≤16.8ms, пауз>50ms0.
Все CPU/cold/draw/manager budgets проходят. Metal/M1 Pro,100000
resident/computed/submitted/in-frustum, все identities/центры проверены;
renderer/geometries/textures/listeners стабильны. Это headless synthetic,
не monitor presentation/реальный S-100k/вся Фаза8.

Backend242/242 и frontend222/222/coverage/build повторены. Functional S-100k
с partial failure/revision/датами/Now/реверсом и непустой100k rebase повторно
прошли. [Navigation recheck](navigation_stress_recheck.json): camera p95/max
0.1/1.0ms, apply0.2/1.5ms, LOD0.1/0.4ms — все прежние лимиты выполнены;
12 resource cycles без роста. Исторический camera11ms не воспроизвёлся,
его причина не объявлена исправленной, исходный FAIL сохранён отдельно.

Финальный publish gate: все7 команд завершились сexit0 — functional100k,
непустойrebase, fixture down, ordinary restore, navigation, navigation_regions,
depth/poles. [Отчёт](publish_checks_report.json), [Земля/Меркурий](navigation_regions_stress_report.json),
[Depth](depth_stress_report.json). Обычный compose без override, health3471.
