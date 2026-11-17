# Проверки и измерения

Команды — [tests/README](../tests/README.md). Ниже: SQLite delivery/backup/
restore/module split2026-11-16; актуальный temporal slice — в последнем разделе.

| Проверка | Результат |
|---|---|
| Backend |307tests, branch-aware coverage96.16%, sectors100% |
| Frontend |222tests, statements/lines/branches/functions97.84/99.03/91.41/98.23% |
| Builds |production seed-free context, test image, frontend PASS; chunk>500kB warning |
| Chrome |physical13/13, legacy10/10 |
| Offline numerical |100Horizons/DE441vectors, max0.002420538km; 1km regression tolerance не absolute accuracy |
| SQLite lifecycle |network: none clean3471, patch→backup→test-volume loss→restore, 9HTTP hashes/cards/order/metadata/revisions exact; иной bootstrap не заменяет working DB |
| Отказы |checksum/schema/capability/corruption, no-clobber, concurrent writers/old readers, SIGKILL recovery, copy/fsync/pre-rename failures |

Независимый reviewer: код/логи; lead: Docker/Chrome. CI пороги:
backend≥95%, sectors100%, frontend statements/lines/functions/branches≥95/96/96/85.
Unit WebGL mocked; реальные shader/picking/resources проверяет Chrome.
CI success7f66098/fd0b1ca не подтверждают текущие незакоммиченные изменения.

Отдельная проверка упрощения Compose/docs: `make test` и `make coverage` —
307/96.16%/sectors100%; sectors/S-100k/legacy профили healthy на5174,
S-100k Chrome4/4; network: none backup→test-volume loss→restore сохранил
9API hashes/DB bytes/revisions. Frontend/обычный Chrome выше — прежняя приёмка.

## Сохранённые benchmarks

| Отчёт | Главный результат и граница |
|---|---|
|[backup](reports/backup_budget_report.json)|100k/1млн backup0.388/3.946s, restore0.393/3.909s; RSS49.40/142.52MiB; extra disk≈73.43/746.67MiB|
|[startup](reports/startup_budget_report.json)|100k/1млн warm readiness1.147/4.108s включая integrity0.297/3.277s; API RSS65.20/80.19MiB|
|[incremental](reports/incremental_budget_report.json)|fixed patch100k/1млн local9.44/11.13ms, total2.28/24.25s; 1000affected rows, не max region|
|[import](reports/import_budget_report.json)|synthetic SBDB100k/1млн12.29/130.19s, RSS55.76/55.69MiB|
|[S-100k](reports/s100k_report.json)|headless Metal12cycles/19windows/11475RAF, no pauses>50ms, cold3.298s; frame p95≤16.8ms, не monitor presentation|

Числа/бюджеты/версии/среда/ограничения — в JSON. Исторические замеры по source
hashes: startup до pinned-release3scan cold path,
backup до mechanical module extraction, renderer/import — предыдущие версии.
Текущий cold readiness не измерялся. Copy/hash/integrity/full legacy —
O(N); SQLite integrity RSS растёт, backup не создаёт полный Python list.
Одиночные runs без CPU isolation/page-cache flush не distributions/SLA;
sampled disk может пропускать краткие пики/удерживаемые unlinked inodes.

Покрыты null/zero/provenance, wire golden/ETag weak-list-star/Unicode,
UTC/TDB/frame/parent/time revision, cancellation/admission/timeout/recovery и
Float64→linear GPU/rebase. Старые camera outliers и неполные stress runs —
[HISTORY](HISTORY.md). Power-loss durability, body/model DB registry, реальный
S-100k, массовый physical streaming/LOD и аппаратные60+fps остаются открыты.
Raw logs/screenshots/coverage — вне repo; постоянный report — с датой/версией/
методом/ограничениями.

## Ограниченный SQLite/API load sprint6.1–6.3 (2026-11-17)

[Единый отчёт](reports/api_load_report.json): 100k/1млн, concurrency1/4/16,
3process-cold repeats, 6warm windows×128requests, отдельные300s sustained16;
288384timed requests, ошибок0. Cold — новый backend, не холодный OS page cache.
Полная пагинация большого сектора: 66671/666671карточек, 131/1303страниц,
порядок/cards/null точны; locks/conflicts/old readers/failure/HTTP publication PASS.
Исправлены filtered legacy304 до лимитов, frontend late responses/cache accounting;
карточки семей>4096 теперь постраничны: память bounded, latency O(family pages).
Одновременные cache misses одного ключа делят одну сборку;
поиск хранит serialized ответы по revision/query/limit в общем прежнем8MiB
filtered/search cache. Sector cache остаётся отдельным8MiB. Fill coordination
ограничена активными sync workers вне byte budget payload cache.

| Метрика |100k|1млн|
|---|---: |---: |
|Backend baseline RSS MiB|65.36–65.41|80.53–80.57|
|Backend peak RSS MiB, включая startup|80.88|175.11|
|Backend post-window RSS MiB|70.75–79.02|85.93–96.17|
|300s throughput req/s|453.87|453.39|
|300s repeated search-no-match p50/p95/p99 ms|25.59/61.01/125.10|26.00/59.80/118.74|
|300s page p50/p95/p99 ms|29.79/72.66/141.76|30.53/72.33/133.22|
|300s late RSS range MiB|0|0|
|Fixture build / successful writer seconds|6.13/3.44|69.26/32.89|

Максимальный page response254418bytes<2MiB. Все18runs/два300s окна прошли
прежние diagnostic budgets: max matrixp95 161.357/239.017ms≤500ms.
Report passed=true; previous_run сохраняет прежние549.957/568.561ms page,
501.763ms search, 543.795ms no-match. Это диагностика, не принятый latency SLA.
При росте N repeated-key throughput уменьшается≈0.10%.
Это bounded cache, не постоянное время substring поиска: новые queries — SQL
scan O(N), зависят от совпадений/плотности.
Fixture/copy/hash/integrity/legacy — O(N), не часть bounded API latency.
Два300s окна/повторные RSS подтверждают стабильность этого workload,
не асимптотику/многочасовую работу/все cache-key distributions.
Driver+generator — отдельный от backend процесс (peak480.15MiB), без взаимной
изоляции. Endpoint tails в матрице: всего16samples;
в sustained на endpoint17024/17008samples.
AppleM1Pro16GiB, Docker VM10CPU/15.60GiB, без container CPU/memory caps;
OS cache не очищался, CPU isolation нет (возможна фоновая нагрузка хоста).

Полный frontend: 23suites/242tests PASS, coverage97.65/99.07/91.13/98.16%
(statements/lines/branches/functions), пороги соблюдены; build PASS.
Missing bodyAssets.js исправлен явным пустым manifest без выдуманных карт;
loader failure/disposal и null orientation покрыты регрессиями.
Chrome13/13 PASS на новом frontend bundle/обновлённом backend.
Backend после исправления: 314tests, branch coverage96.15%, sectors100%.
Untimed independent nearby/search/card/locate oracles PASS100k/1млн,
fixture logical SHA+revision совпали с timed run.
32новых последовательных search keys/размер: точные match/no-match PASS, p50/p95/max 24.35/31.11/33.62ms и165.69/171.62/174.18ms.
Это uncached наблюдение, не concurrent16 novel-query приёмка/SLA.
Production backend/frontend/test images PASS. Reviewer независимо проверил
код/конкуренцию/cache lifecycle/accounting/целевые frontend regressions.
Штатный volume сохранён, health3471. Общий этап6 и массовый physical streaming
остаются открытыми.

## Temporal physical streaming slice (2026-11-17)

[Единый машинный отчёт](reports/physical_streaming_report.json),
[контракт/предварительные бюджеты](PHYSICAL_STREAMING.md).
Пять реальных DE440s centers: безусловный дисковый candidate sector и текущий
AABB после requested-time solver; snapshot не исключает движущееся тело.
100k/1млн проверены отдельно на явно synthetic affine trajectories,
SQLite4D Rtree365-day swept envelopes и том же production API/PositionWork/
manager/Float64 layer/WebGL path. Это не массовые реальные положения.

Пределы соблюдены: 16candidate sectors×128members≤2048новых
записей, old+staged≤4096, 4HTTP/solver workers без backend backlog,
256KiB response, 4MiB serialized/32MiB decoded admission estimate. Плотная
область сверх16кандидатов→413 без усечения; false positives допустимы.
Неподдержанная дата→422, unknown=null; immutable readers — прежняя ревизия
либо409/полный повтор. Index/position/registry/time bindings проверены.

Три свежих процесса на размер, 96переходов в первых двух и180s в третьем;
две120s Chrome windows, три sparse/dense/empty/overflow иdispose/recreate цикла.
Cold=process/application cache, OS page cache не очищался.
Ниже — sustained; все распределения повторов/выбросы — в JSON.

|Метрика|100k synthetic|1млн synthetic|
|---|---: |---: |
|180s переходы|4851|5065|
|Selection HTTP p50/p95/p99 ms|9.287/11.633/14.703|9.153/11.328/13.032|
|Sector positions HTTP p50/p95/p99 ms|15.945/29.971/46.180|15.231/27.581/40.595|
|Chrome accepted frame p50/p95/p99 ms|80.8/100.0/109.6|81.2/100.2/110.1|
|Backend peak/post RSS MiB|76.109/76.109|76.102/76.102|
|Backend late60s RSS range MiB|0|0|
|First usable Chrome scene seconds|2.033|1.526|
|Index build / integrity seconds|3.204/0.131|32.961/1.373|

Backend baseline53.40–53.42MiB; generator/driver RSS отдельно в отчёте.
Index construction/integrity/publication — O(N), раздельные timings в JSON;
полного catalog copy/hash в temporal request path нет. AppleM1Pro16GiB,
Docker VM10CPU/15.60GiB, cgroup=max, shared host без CPU isolation.

Chrome resident≤2048, computed/submitted dense2032 (16null), in-frustum отдельно;
peak active4/queue16, 11cancelled selections/4HTTP на размер, late responses0.
После dispose geometry/texture/program=0. Whole-tab heap≈44.4/44.5MiB peak,
baseline/post и10s windows записаны; GPU driver memory не измерена.
Sustained RAFp95/p99=16.7/16.8ms, пауз>50ms/longtasks нет. Callback CPU
p95=0.2/0.3ms — только LOD+submission; полный main-thread CPU budget не принят.
SwiftShader не аппаратные60fps.

Ограничения: cold longtasks1867/1382ms; recovered503 retries1/2,
accepted-frame maxima1081/1082.2ms. Первичные cold outliers сохранены отдельно.
Измеренные diagnostics прошли; это не SLA/доказательство асимптотики памяти.

`make coverage`: 336tests PASS, branch-aware96.40%, sectors100%; frontend
24suites/255tests PASS, statements/branches/functions/lines97.63/91.22/98.17/99.08%,
build PASS; production/test Docker builds PASS, warning frontend chunk>500kB.
Chrome ordinary13/13, recovery7/7. Reviewer: повторно 37 backend tests и весь
frontend; проверены numeric/browser reports, fixture/source hashes; блокеров нет.
Все100Horizons vectors пяти реальных centers PASS, max0.002420538km при1km regression tolerance, не absolute uncertainty.
Исправлены обход publication-specific interval в прямых sector/object reads,
отсутствующая temporal revision у unknown real object и длина synthetic registry
revision для pinned paging. Новые модели/тела/UTC не добавлены.

Весь3.3, этап6, массовые реальные positions/general registry/hardware60fps
открыты. Обычная сцена/SQLite/API результаты сохранены;
ordinary volume не использовался для fixtures/patches, не удалялся.
Тестовая сцена остановлена, обычный compose healthy, health3471.
