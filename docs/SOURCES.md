# Источники и `sources/1`

[data/source_registry.py](../data/source_registry.py) — явный opt-in:
Sun 10, Earth 399, Moon 301, Mercury 199, Venus 299, offline DE440s.
BSP discovery не расширяет состав; body_center ≠ barycenter; NAIF 0…9 — барицентры.
[Физический/API-контракт](COORDINATES.md), [аудит и пробелы](SOURCE_AUDIT.md).

Объект: id/target/identity_type/model_id/name/kind/color. Модель: provider/model,
revision/solver/asset/SHA-256/URL, frame/axes/origin/unit/time_scale/интервалы.
provider_revision=asset-sha256-… — версия актива; source_epoch/accuracy=null.
Известная эпоха/ковариация пока не поддержаны. Реестр immutable;
SHA-256 включает состав/порядок/метаданные, дубликаты identity отвергаются.

`GET /api/sources/v1/objects?limit=128&offset=0&q=moon&revision={sha256}`
→ version/revision/objects/models/total/next_offset (в конце null).
q — case-insensitive substring ID/имени; offset в фильтре, total всего реестра.
limit 1…128, offset 0…1000000, q ≤128, revision ≤64 символов.
422 неверные параметры; 413 страница >256 KiB; 409 stale revision до ETag;
304 без тела; Cache-Control: public,max-age=0,must-revalidate.
Объект ≤1024 Б, модель ≤8192 Б, ≤128 моделей. Positions revision:
`positions1-{registry_sha256}-hierarchy1-ssb1`, отдельно registry_revision;
contract содержит supported_ids_total/capabilities_url и первые ≤128 supported_ids.
Frontend: первая страница/последний поиск. Backend: резидентный реестр, линейный
поиск; дисковый реестр моделей/обновление без рестарта открыты.

`data/import_sbdb.py`: opt-in [SBDB Query API v1.0](https://ssd-api.jpl.nasa.gov/doc/sbdb_query.html),
full_name/pdes/a/per/diameter = имя/identity/AU/days/km. Невалидные числа — отказ,
null сохраняется; неполная орбита не даёт positions. Один ограниченный ответ,
count/fields/signature/полнота JSON проверяются; без paging/resume, повтор с начала,
pin SHA-256. ID/owned deletes/manifest — [SECTORS](SECTORS.md).

Цель — все известные тела на дату обновления. Учёт по источнику: дата/ревизия,
доступный/импортированный объём, фильтры/лимиты/пробелы, aliases; TOP не полнота.
Рабочие body/model данные — в БД; Python opt-in реестр переходный.
[SQLite startup](STARTUP.md) работает offline. BSP — отдельный
версионированный ресурс модели; кэш учитывает model/revision/time/frame.
Автообновления после
валидации открыты: неполный импорт не удаляет пропуски, ошибка сохраняет публикацию.
[Этапы](../ROADMAP.md).
