# Краткая история

Статус — [ROADMAP](../ROADMAP.md), приёмка — [TEST_COVERAGE](TEST_COVERAGE.md).
Прежние документы/отчёты в Git:
[4fe4263](https://github.com/Vibecode-org/astroverse/tree/4fe426355dcb273020971308134df9a360d39282/docs).

| Этап | Результат |
|---|---|
| Legacy0–2 | L0/L1/L2,picking/shared resources,Python↔JS v1/v2,gzip/ETag; координаты иллюстративные |
| Physical minimum | positions/1,5DE440s centers,100Horizons vectors,Float64 hierarchy,6DoF/rebase/log-depth |
| 2026-11-10 SBDB3.7-A | bounded HTTP→SQLite,provenance/explicit deletes/atomic publication |
| 2026-11-12 synthetic S-100k |100×1000через physical path,19clean windows; пользовательский frame p95≤16.8ms,real/monitor acceptance открыта |
| 2026-11-15 local3.7-B | bounded normalized card/graph/search/cells update; полная публикация остаётся O(N) |
| 2026-11-16 startup/delivery | pinned SQLite без seed при build/startup,working volume priority,explicit migration |
| 2026-11-16 backup/restore | patched working publication восстановлена побайтно после потери test volume; иной bootstrap её не меняет |
| Разделение модулей | schema/codecs,HTTP serialization/legacy JPL,frame validation,patch region/shared locks,LOD detail/picking |

Navigation camera max9.3/11ms превышали8ms; причина не установлена,
порог не повышен. Повтор дал1ms. SwiftShader32×64fixture проверял2016computed/
32null,48resource cycles; GPU/driver memory и аппаратныеfps этим не приняты.
Прерванные/неполные S-100k runs не PASS; исходный16.667ms был провален.
Legacy resource baseline исправлен: ожидание CDN loads/errors и GPU прогрев.

Пять [машинных benchmarks](reports/) сохраняют точные measured values,source hashes,
методику/ограничения. Старый startup cold замерял2integrity scans; текущий pinned
release использует3,новый cold timing не измерен. Функциональные
регрессии не обновляют performance измерения.
