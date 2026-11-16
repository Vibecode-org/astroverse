# SQLite-каталог и snapshot API

Runtime читает `DiskCatalog`: schema2 хранит карточки, ordinal, поисковый текст,
индексы, секторы/R-tree, metadata и legacy v1/v2 BLOB. На запрос открывается
read-only snapshot; atomic rename не меняет уже открытые ответы/BLOB.
Запуск, поставка, backup/restore и migration — [STARTUP](STARTUP.md).

## Координаты и разбиение

`coordinates/1` — каталоговые снимки, не положения на выбранную дату.
Frame/epoch/origin/accuracy не выводятся из имени источника; неизвестное — null.
Legacy v2 содержит render-координаты. Физическая сцена использует отдельный
`positions/1` пяти проверенных центров; снимки туда не передаются.
Контракты — [COORDINATES](COORDINATES.md), [HIERARCHY](HIERARCHY.md).

Семейство `parent` неделимо, сектор задаётся позицией корня; циклы, сироты и
cross-scale связи отклоняются. Solar — `solar:system`, неизвестная позиция —
`<scale>:unlocated` с null bounds, доступная для карточек/поиска.

Сетка по умолчанию 32 ly, мягкий порог 4096 объектов, octree до 16 уровней.
ID — `<scale>:<frame>:ix:iy:iz[/octant…]`; большие неделимые семьи могут
превышать порог. Переразбиение меняет ID листьев. Предел R-tree — 3e38 ly;
непредставимые численные конфигурации отклоняются. Nearby пересекает сферу
с bounds корней, отдельно по frame/scale; это не точный список тел и не frustum.

## HTTP `spatial/1`

| GET `/api/spatial/v1/…` | Результат / предел |
|---|---|
| `contract` | `coordinates/1` |
| `nearby?scale=local&frame=equatorial&x=0&y=0&z=0&radius=32` | Листья + `snapshot`; `limit` 1…128 |
| `sectors/{id}?limit=512&after={object_id}` | Страница по ID, exclusive cursor; `next_after` либо null |
| `objects/{id}/sector` | Сектор семейства и статус координат объекта |

Nearby: `local/galaxy`, `equatorial/galactic`, центр ±1e12 ly, радиус 0…1e6 ly.
Solar/unlocated доступны по ID. Страница: 1…512 карточек, `after` ≤512 символов;
семейство замкнуто в листе, не обязательно в странице. Ответ ≤2 MiB.
Превышение числа листьев/bytes — 413 без усечения; неизвестный ID — 404,
неверные параметры или любой `at` — 422, недоступная публикация — 503.

`snapshot` фиксирует общую ревизию между запросами: несовпадение даёт
409 `snapshot_changed` до ETag; выборку начать заново. Без параметра каждый
запрос согласован отдельно. Страница сообщает `X-Catalog-Snapshot`, включая 304.
ETag листа зависит от его revision/limit/after; независимый patch его сохраняет.
Nearby/locate используют общую ревизию. Weak/list/`*` поддерживаются;
лимиты проверяются до 304. Курсор без snapshot не гарантирует согласованную
пагинацию между публикациями.

LRU snapshot-ответов — 8 MiB (`ASTROVERSE_SECTOR_CACHE_BYTES`); filtered legacy —
отдельные 8 MiB (`ASTROVERSE_BINARY_CACHE_BYTES`). Это бюджеты кэшей, не RSS.
Filtered legacy ≤4096 объектов/8 MiB, иначе 413. Полные JSON/v1/v2 stream по 64 KiB
без полного Python-каталога, но трафик O(N); исходный порядок и wire format
сохранены. Поиск — SQL substring scan, до 500 результатов, не inverted index.
Frontend snapshot-кэш ограничен 4 MiB/4096 декодированными карточками запроса;
он обслуживает карточки. Physical admission/selection — [PHYSICAL_LOD](PHYSICAL_LOD.md).

## Подготовка и публикация

```bash
# SOURCE — явно сохранённый JSON, доступный контейнеру; TARGET — кандидат.
python -m backend.prepare_runtime SOURCE TARGET
```

Streaming builder читает ijson по объекту; graph, сортировки и strings живут
на диске, SQLite cache 8 MiB/`temp_store=FILE`. `data/sectors.py` сохраняет
списочный builder для тестов/малых явных каталогов. JSON остаётся API/fixture/
tooling-форматом; изменение JSON не сбрасывает рабочие patches при рестарте.

Writers используют постоянный `data.publication.publication_lock`, проверяют
expected revision и публикуют проверенный/fsync кандидат atomic rename.
Lock inode сохранять. Старые readers держат прежний inode; ошибка/SIGKILL до
rename сохраняет прежнюю публикацию. Следующий writer удаляет только своё
private staging. Самовольная запись SQL поверх активного inode не поддерживается.

### Ограниченный этап 3.7-B: локальный writer

```python
from data.incremental_catalog import publish_changes
metadata = publish_changes(path, expected_revision=revision,
                           upserts=changed_cards, deletes=removed_ids, metrics={})
```

Предел входа — 4096 upserts +4096 deletes, вместе 8 MiB. Indexed closure и
переразбиение старых/новых базовых ячеек ограничены объединением 65536 ID,
64 MiB payload (максимум старого/нового по ID), 4096 cells. Превышение даёт
`ResultLimitExceeded` до copy; это предел patch-работы, не размера каталога.

`incremental_region.py` проверяет семьи и split/merge; меняются только effective
upserts/search rows и затронутые секторы. Исходный порядок старых ID сохраняется,
новые добавляются по ID. No-op не меняет inode/revision, но устаревший expected
revision всё равно отклоняется (`RevisionConflict`). Старый import manifest
переносится в `previous_import_manifest` после административного patch.

Writer требует `incremental_schema=1`; старая schema2 читается, но для patch
нужна явная полная подготовка с индексами и сохранением её текущих карточек.
SQLite copy, общий hash, полные v1/v2 и integrity/FK остаются **O(N)**.
Метрики разделяют локальный граф/update и полные copy/hash/legacy/validation/
publication; total включает lock и cleanup. Нужны staging/journal/binary spools
и место старым readers. Это ограниченная локальная работа, не O(изменений)
публикация и не закрытие всего 3.7-B/общего body-model registry.

### Прямой SBDB import: ограниченный 3.7-A

```bash
python -m data.import_sbdb PATH --expected-revision HEX --limit 400
```

Один HTTP→bounded events→staging SQLite→normalization/merge→проверки→rename.
Upsert астероидов по `pdes`; пропуск во входе сохраняет запись. `--delete-id`
удаляет только явно перечисленные принадлежащие адаптеру ID, отсутствующие
во входе (≤4096). Новый ID — `sbdb:a:{pdes}`; старые source IDs сохраняют identity,
legacy name-match допустим только однозначный. Overrides сохраняются;
registry физических центров не расширяется.

Metadata `catalog-import/1` хранит source/query/input SHA, версии и timestamps,
semantic/parent revisions. Карточки хранят input hash/версии; получение не эпоха,
неизвестные frame/epoch/accuracy — null. Повтор без semantic change не публикуется;
timestamps не входят в revision. Pin входа —`--expected-sha256`.

Пределы: 2 млн строк, 1 GiB, пять полей, 4096 wire bytes/token, nesting 4, read ≤64 KiB.
Defaults socket 30s/deadline 600s/retries 2 (допустимо 0…3); transport/429/5xx
повторяются целиком, плохие schema/JSON/полнота — нет. Redirects и paging/resume
запрещены. Lock/expected revision проверяются до HTTP. Полные merge/graph/
индексы/VACUUM/v1/v2 и повторная валидация остаются **O(N)**.

Проверки и измерения — [TEST_COVERAGE](TEST_COVERAGE.md),
[tests/README](../tests/README.md), [incremental report](reports/incremental_budget_report.json).
