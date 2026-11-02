# Бинарный формат каталога v2

Спецификация и контракт для бинарного каталога объектов Astroverse (версия 2). Реализован в `data/catalog.py` (Python), `frontend/src/data/readBinaryCatalog.js` (JS) и `backend/app.py` (HTTP эндпоинт).

## Зачем

JSON-каталог из 100 000 объектов занимает сотни мегабайт и парсится долго. Бинарный v2-формат — compact SoA (structure-of-arrays) с UTF-8 строковой таблицей: примерно 130 байт/объект, парсинг ~130 мс на 100 000 объектов (~4 мс на 3 471).

## Формат файла

Все числа little-endian. Заголовок:

| Поле | Размер | Описание |
|------|--------|----------|
| magic | 4 байта | `"ASTV"` |
| version | uint32 | `2` |
| count | uint32 | число объектов |
| header_size | uint32 | размер заголовка (включая таблицу смещений) |
| section_count | uint32 | `19` |
| offsets | uint64 × 19 | смещение каждой секции от начала файла |

После заголовка идут секции в фиксированном порядке (19 шт., таблица в `BINARY_V2_SECTIONS`):

1. `positions` — float32, `count × 3` (x, y, z)
2. `sizes` — float32, `count`
3. `colors` — uint32, `count` (RGBA packed)
4. `kinds` — uint8, `code → KIND_NAMES`
5. `flags` — uint8, `bit0 = has parent, bit1 = has jet`
6. `parents` — int32, `index в массиве, −1 если нет`
7. `scales` — uint8, `0 = solar, 1 = local, 2 = galaxy`
8. `radius_km` — float32, `count`
9. `radius_earth` — float32, `count`
10. `au` — float32, `count`
11. `period_days` — float32, `count`
12. `temperature_k` — float32, `count`
13. `id_offsets` — uint32, `count`
14. `id_lengths` — uint32, `count`
15. `name_offsets` — uint32, `count`
16. `name_lengths` — uint32, `count`
17. `latin_offsets` — uint32, `count`
18. `latin_lengths` — uint32, `count`
19. `strings` — байты, все id/name/latin подряд (последняя секция, без выравнивания)

Все секции кроме `strings` выровнены по 4 байта. Числовые null кодируются как `0.0`; `scale` неизвестен → `255` (декодируется как `"local"`).

## HTTP

- `GET /api/objects` — JSON (по умолчанию, для обратной совместимости)
- `GET /api/objects?format=v2` — v2 бинарный (`Content-Type: application/octet-stream`, заголовок `X-Catalog-Format: v2`)
- `Accept: application/vnd.astroverse.catalog.v2` — тоже v2
- `Accept: application/octet-stream` — v1 бинарный (26 байт/объект, без строк)

### Кэширование

Любой ответ `/api/objects` (JSON, v1, v2) несёт:

| Заголовок | Значение |
|---|---|
| `ETag` | `"<ревизия каталога>-<версия>-<q>-<kind>-<scale>"` |
| `Cache-Control` | `public, max-age=0, must-revalidate` |
| `Vary` | `Accept` |

Ревизия каталога — `size-mtime_ns` файла, из которого он загружен, поэтому
пересборка каталога меняет валидатор. `q` percent-encode-ится: заголовки —
latin-1, и кириллический запрос иначе ломает ответ. `Vary: Accept` обязателен:
один URL отдаёт JSON, v1 или v2 в зависимости от `Accept`.

Запрос с `If-None-Match` (weak `W/"…"`, сильный ETag или список через запятую)
возвращает `304 Not Modified` без тела. На 100k это ~2 мс и 0 байт вместо
повторной передачи 2.46 МБ. nginx ослабляет ETag gzip-ответов до `W/"…"`,
поэтому сравнение нормализует `W/`.

v1 не ломается; v2 добавляется рядом. Фронтенд грузит `/api/objects?scale=solar` (JSON, солнечная система) + `/api/objects?format=v2` (полный бинарь). При ошибке бинаря — fallback на полный JSON с `console.warn`.

## Что внутри (и чего нет)

v2 содержит: позиции, размер, цвет, вид, флаги, индекс родителя, scale, радиусы, орбитальные параметры, id/name/latin.

v2 НЕ содержит: description, facts, ra, dec, галактические координаты. Карточка объекта догружается через `/api/objects/{id}`; поиск — через `/api/search?q=`.

## Экзопланеты

Экзопланеты раскладываются по орбитам фронтендом (см. `buildDeepSky.js`, `animation.js`), их бинарная позиция не используется. Бинарная позиция используется только для корневых звёзд и кластеров (без `parent`).

## API чтения/записи (Python)

- `encode_binary_catalog_v2(items) -> bytes` — собрать blob
- `write_binary_catalog_v2(path, items)` — атомарная запись
- `read_binary_catalog(buffer)` — диспатч v1/v2
- `read_binary_catalog_v2(buffer)` — только v2
- `validate_catalog(items)` — валидация перед записью

## Декодирование строк на фронтенде

`readBinaryCatalog.js` декодирует `id`/`name`/`latin` батчем, а не по одной
строке:

1. Вся секция `strings` декодируется одним вызовом `TextDecoder.decode`.
2. `countUnits` считает UTF-16 code units по lead-байтам (continuation-байты
   пропускаются, 4-байтовая последовательность даёт суррогатную пару).
3. Каждая строка вырезается через `text.slice(unitStart, unitStart + units)` по
   смещениям из таблиц.

Это убирает фиксированную стоимость `TextDecoder` на вызов: на 100k было 300k
вызовов и ~135–166 мс, стало ~122–164 мс (медиана 129 мс) при том же
результате. Быстрый путь отказывается и падает на построчный `decodeTable`,
если таблицы не отсортированы по возрастанию, перекрываются, выходят за границы
или UTF-8 невалиден (декодер подставит `U+FFFD`, и подсчёт юнитов разойдётся).

Компромисс по памяти: строки, полученные `slice`, держат родительскую строку
всего блока (~12 МБ на 100k), пока жива хотя бы одна из них. Для каталога,
который живёт весь сеанс, это приемлемо; для стриминга по секторам (Фаза 3)
блок нужно будет освобождать вместе с сектором.

## Тесты

- `tests/test_catalog.py` — 6 тестов v2 (roundtrip строк/scale/parents, выравнивание заголовка, совпадение с v1, эквивалентность seed JSON, dangling parent, corrupt/truncated).
- `tests/test_api.py` — API v2/search, индексация каталога и ETag/304
  (включая поиск по каждому полю, запрет матча поперёк полей и пересборку
  индекса при подмене каталога).
- `tests/browser_smoke/smoke_binary.py` — v2 в браузере и gzip-транспорт.

## Размер

| Каталог | Объектов | v2 бинар | На объект | По сети (gzip) |
|---------|----------|----------|-----------|----------------|
| seed (реальные) | 3 471 | 319 979 Б | ~92 байт | 83 783 Б (3.8×) |
| 100k (synthetic) | 100 000 | 13 000 172 Б | ~130 байт | 2 456 590 Б (5.3×) |

100k укладывается в порог < 20 МБ. Для 1 млн линейная оценка — **~130 МБ**
(71 МБ числа + 59 МБ строки), а не 30 МБ: целевые 30 МБ относятся к v1-core
(26 байт/объект) без строк. Чтобы отдавать 1 млн, нужен стриминг по секторам
(Фаза 3) или сжатие/отдельная компактная выдача метаданных. На synthetic-наборе
gzip даёт ~2.45 МБ на 100k (≈24.5 МБ на 1 млн), но для реальных данных это не
гарантировано.

## Транспорт: gzip

`frontend/nginx.conf` включает `gzip_types ... application/octet-stream` и
`gzip_vary on`, поэтому v2 (и v1 binary) отдаются сжатыми:

- `Accept-Encoding: gzip` → `Content-Encoding: gzip`, `Vary: Accept-Encoding`,
  ответ chunked (без `Content-Length`)
- `Accept-Encoding: identity` → без сжатия, с `Content-Length`
- Тело после распаковки побайтово совпадает с файлом `objects.v2.bin`

gzip экономит только трафик: в памяти всё равно лежит распакованный blob, а
время парсинга не меняется (его ускоряет батчевое декодирование строк, см.
выше). Тесты транспорта —
`tests/browser_smoke/smoke_binary.py::TestBinaryTransport`.
