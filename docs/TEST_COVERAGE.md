# Проверки и измерения

Команды — [tests/README](../tests/README.md). Последняя полная приёмка кода:
2026-11-16,SQLite delivery/backup/restore/module split.

| Проверка | Результат |
|---|---|
| Backend |307tests,branch-aware coverage96.16%,sectors100% |
| Frontend |222tests,statements/lines/branches/functions97.84/99.03/91.41/98.23% |
| Builds |production seed-free context,test image,frontend PASS; chunk>500kB warning |
| Chrome |physical13/13,legacy10/10 |
| Offline numerical |100Horizons/DE441vectors,max0.002420538km;1km regression tolerance не absolute accuracy |
| SQLite lifecycle |network:none clean3471,patch→backup→test-volume loss→restore,9HTTP hashes/cards/order/metadata/revisions exact; иной bootstrap не заменяет working DB |
| Отказы |checksum/schema/capability/corruption,no-clobber,concurrent writers/old readers,SIGKILL recovery,copy/fsync/pre-rename failures |

Независимый reviewer проверил код/логи; Docker/Chrome запускал lead. CI пороги:
backend≥95%,sectors100%,frontend statements/lines/functions/branches≥95/96/96/85.
Unit WebGL mocked; настоящий shader/picking/resources проверяются Chrome.
Старые CI success7f66098/fd0b1ca не подтверждают текущий незакоммиченный набор.

Упрощение Compose/docs проверено отдельно: `make test` и `make coverage` —
307/96.16%/sectors100%; sectors/S-100k/legacy профили healthy на5174,
S-100k Chrome4/4; network:none backup→test-volume loss→restore сохранил
9API hashes/DB bytes/revisions. Frontend и обычный Chrome выше — прежняя приёмка.

## Сохранённые benchmarks

| Отчёт | Главный результат и граница |
|---|---|
|[backup](reports/backup_budget_report.json)|100k/1млн backup0.388/3.946s,restore0.393/3.909s;RSS49.40/142.52MiB;extra disk≈73.43/746.67MiB|
|[startup](reports/startup_budget_report.json)|100k/1млн warm readiness1.147/4.108s включая integrity0.297/3.277s;API RSS65.20/80.19MiB|
|[incremental](reports/incremental_budget_report.json)|fixed patch100k/1млн local9.44/11.13ms,total2.28/24.25s;1000affected rows,не max region|
|[import](reports/import_budget_report.json)|synthetic SBDB100k/1млн12.29/130.19s,RSS55.76/55.69MiB|
|[S-100k](reports/s100k_report.json)|headless Metal12cycles/19windows/11475RAF,no pauses>50ms,cold3.298s;frame p95≤16.8ms,не monitor presentation|

Точные числа/бюджеты/версии/среда и ограничения — в JSON. Это исторические
замеры указанных source hashes: startup до pinned-release3scan cold path,
backup до mechanical module extraction,renderer/import — предыдущие версии.
Текущий cold readiness не измерялся. Copy/hash/integrity/full legacy остаются
O(N); integrity SQLite RSS растёт,полный Python list при backup не создаётся.
Одиночные runs без CPU isolation/page-cache flush не distributions/SLA;
sampled disk не учитывает все краткие пики/удерживаемые unlinked inodes.

Проверки охватывают null/zero/provenance,wire golden/ETag weak-list-star/Unicode,
UTC/TDB/frame/parent/time revision,cancellation/admission/timeout/recovery и
Float64→linear GPU/rebase. Старые camera outliers и неполные stress runs —
[HISTORY](HISTORY.md). Power-loss durability,body/model DB registry,реальный
S-100k,массовый physical streaming/LOD и аппаратные60+fps остаются открыты.
Raw logs/screenshots/coverage хранить вне repo; постоянный report требует
даты,версии,метода и ограничений.
