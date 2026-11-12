# Проверки и измерения

Команды — [tests/README](../tests/README.md), контракты —
[COORDINATES](COORDINATES.md), [SECTORS](SECTORS.md), [SOURCES](SOURCES.md).
Сводка измерений относится к 7f66098 и сохранённым source hashes, не к любому
последующему изменению. Очистка документации не является повторным benchmark.

## Автоматические проверки

| Проверка | Результат |
|---|---|
| Backend/Docker |242 теста, OK|
| Backend coverage с branches |98.39%; sectors100%|
| Frontend |222 теста, OK|
| V8 statements/lines/branches/functions |97.83/99.03/91.41/98.23%|
| Vite/Docker build |OK; известный chunk>500kB|
| Независимые Horizons/DE441 |100 векторов, max0.002420538km|
| GitHub CI7f66098 |backend/frontend success|
| GitHub CI очистки fd0b1ca |backend/frontend success|

CI требует backend≥95%, sectors100%; frontend statements/lines/functions/
branches≥95/96/96/85 и build. Unit canvas/WebGL заменены; настоящие GPU,
shader depth, picking и UI проверяются отдельно Chrome MCP.

## Постоянные машинные отчёты

| Отчёт | Что сохранено |
|---|---|
|[s100k_report.json](s100k_report.json)|Профиль, исходные/действующие бюджеты, hashes, Metal baseline,19 стресс-окон, CPU/HTTP/frame distributions, память, численные проверки, неудачные попытки и ограничения|
|[navigation_budget_report.json](navigation_budget_report.json)|Последний обычный navigation, Земля/Меркурий, depth/poles и исторические CPU outliers|
|[physical_budget_report.json](physical_budget_report.json)|32×64 HTTP fixture, admission, timing, память/ресурсы, request correlation|
|[import_budget_report.json](import_budget_report.json)|SBDB HTTP/SQLite100k/1 млн: фазы, RSS, диск, бюджеты|

В JSON `git:revision:path` адресует полный архивный отчёт в Git. Дубли удалены
из текущего дерева; измерения сохранены без округления и не выданы за новый прогон.
Подробная хронология — [HISTORY](HISTORY.md).

## Synthetic S-100k

SQLite100×1000→обычные HTTP/manager/UI/WebGL. Initial/final overview:
catalog/resident/computed/submitted/in-frustum=100000, hidden policy0,1draw call.
Все identities и центры проверены вне измеряемых окон; растровые диски перекрываются.
Metal/M1 Pro,macOS26.3,Chrome157,1920×1080/DPR1, без CPU isolation.

Стресс:12 циклов/19 окон,11475RAF samples/191.59s; худшие p95/p99/max16.8ms,
пауз>50ms0,cold3.298s. Все CPU/cold/draw/manager бюджеты пройдены. Исходный
порог p9516.667ms не был пройден; пользователь согласовал 16.8ms отдельно,
остальные пороги сохранены. Это headless RAF на аппаратном GPU, не monitor
presentation и не приёмка реального S-100k/всей Фазы 8.

Renderer сохраняется,1geometry/0textures,28 учтённых listeners без роста
(включая 2 диагностических error listeners). GPU attributes3670016B плюс столько
же staging; manager≤200000rows/64MiBserialized/512MiBdecoded estimate/4workers.
Это не browserRSS, не driver memory и не доказательство отсутствия любых утечек.
Непустой rebase сохраняет биты 100000 центров,16screen samples:~3e-14CSSpx
при допуске 0.05. Partial failure/revision conflict/manual/Now/ускорение/реверс
и прогресс displayed UTC проверены функциональным runner отдельно от timing.

## Обычная сцена и навигация

Physical13/13,LOD5/5,recovery7/7,UTC bounds4/4,legacy10/10,latency,
navigation7 сценариев/12 циклов,depth/poles и navigation_regions прошли.
Camera p95/max0.1/1.0ms,apply0.2/1.5ms,LOD0.1/0.4ms.
Предыдущий camera11ms outlier не воспроизведён; причина не установлена,
исходная ошибка сохранена в истории отчёта, порог 8ms не повышался.

У Земли submitted все 5computed-центров. Три цикла Меркурия после удаления
>200 млнkm сохраняют physical eye/центры и loading reach; jump0km при допуске 1e-6km.
WebGL readPixels/picking проверяют передний центр, оба порядка, L0/L1,
1e7…1e12km; оба точных полюса сохраняют eye/quaternion, native drag восстанавливается.
Эти сценарии сохраняют renderer/GPU resources/listeners.

## Остальные численные и отказные риски

- DE440s↔Horizons: ICRF/SSB/geometric/km/TDB,20 дат на 5 тел. Допуск 1km —
  регрессионный, accuracy остаётся null. Клиентская арифметика<1e-6km.
- Hierarchy: большие начала/sub-ULP offsets, parent closure, metadata/time/
  revisions, unknown/null, линейные GPU transforms и rebase без мутации центров.
- Manager: cancellation при merge/decode/preparation, atomic publication,
  partial failure/retry409/timeout, несовместимые JD/UTC/revisions, admission,
  drain/slot reuse, hidden-tab scheduler и согласованность picking.
- Каталог/HTTP: schema/identity/parent/cycles, binary Python↔JS, ETag weak/list/*,
  gzip decoded body, Unicode query, page/cache budgets, corrupt artifacts.
- Import: bounded raw staging, truncation/redirect/token/nesting, explicit owned
  deletes, ambiguity, старые readers, concurrent writers, SIGKILL/restart,
  validate/rename/cleanup failures и отказ без повреждения активной ревизии.
- Snapshot R-tree: независимый перебор, bounds/октанты, split/merge/reuse,
  overflow, unlocated и отсутствие подмены requested-time physics снимком.

Обычный compose после fixture/stress восстановлен; проверенный health3471.
Power-loss durability, общий временной индекс, полный DB startup migration,
массовые physical streaming/LOD и реальные 100k остаются открыты.

После очистки повторены backend242/242, frontend222/222 с coverage/build,
Docker build и physical Chrome MCP13/13. Проверены ссылки, точное сохранение
чисел в сводных JSON и PASS оценщика архивного стресса. Сам performance stress
повторно не запускался; указанные timing-результаты остаются измерениями7f66098.

После разделения модулей повторены backend242/242 с coverage98.39%/sectors100%,
frontend222/222 с coverage/build, golden v1/v2 и оба builder entrypoints.
Chrome: physical13/13, legacy10/10 после корректного CDN/GPU прогрева,
navigation_regions (Земля и три дальних цикла Меркурия), synthetic S-100k4/4.
В initial/final S-100k по100000 identities/numeric/resident/computed/submitted/
in-frustum,1draw call, тот же renderer,1geometry/0textures/28listeners.
Now/ускорение/реверс прогрессируют; partial failure/revision conflict проходят.
Это функциональный прогон с probes, без новой приёмки performance/fps.
