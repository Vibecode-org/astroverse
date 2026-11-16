# Бинарный формат каталога v2

Legacy render SoA, не physical positions/эпоха/эфемериды. `/` читает `positions/1`;
`/?scene=legacy` — solar JSON+полный v2, при ошибке binary полный JSON fallback.
ID-фазы орбит экзопланет иллюстративны, в physical не допускаются.

Ownership: `data/catalog.py` — публичный API/JSON I/O; `catalog_schema.py` —
validation; `catalog_binary.py` —v1/common render primitives;
`catalog_binary_v2.py` —v2; `frontend/src/data/readBinaryCatalog.js` —decoder;
`backend/catalog_responses.py` —SQLite streaming/cache, `app.py` —HTTP dispatch.

## Формат файла

Little-endian header: `ASTV`(4B),version uint32=2,count uint32,
header_size uint32=172,section_count uint32=19,offsets uint64×19 от начала файла.
Секции фиксированного порядка, каждая count элементов, кроме указанных:

| № | Секция | Тип |
|---|---|---|
|1|positions|float32×count×3: x,y,z render units|
|2|sizes|float32|
|3|colors|uint32 packed RGBA|
|4|kinds|uint8, KIND_CODES|
|5|flags|uint8:bit0 parent,bit1 jet|
|6|parents|int32 index,−1 отсутствует|
|7|scales|uint8:solar0/local1/galaxy2|
|8–12|radius_km,radius_earth,au,period_days,temperature_k|float32|
|13–18|id_offsets,id_lengths,name_offsets,name_lengths,latin_offsets,latin_lengths|uint32|
|19|strings|UTF-8 bytes id/name/latin, byte offsets/lengths|

Все секции кроме strings выровнены по4B. Legacy numeric null→0.0;
unknown scale255 декодируется local. Это lossy legacy encoding, не правило
unknown для physics. Parents/границы/offsets/truncation проверяются.
V1 header `ASTV,version uint32=1,count uint32,offset uint64=20`, далее
positions/sizes/colors/kinds/flags/parents:26B/object, без строк.

## HTTP

`/api/objects`→JSON; `?format=v2` или Accept vendor
`application/vnd.astroverse.catalog.v2`→v2; Accept `application/octet-stream`→v1.
Binary Content-Type `application/octet-stream`, X-Catalog-Format v1/v2,
X-Object-Count. Карточка `/api/objects/{id}`, поиск `/api/search?q=`;
description/facts/ra/dec отсутствуют в v2.

SQLite prebuilt full v1/v2 читаются блоками64KiB, JSON потоком;
filtered≤4096objects/8MiB,иначе413; cache≤8MiB. ETag непрозрачный от snapshot
revision/версии/filters; Cache-Control `public,max-age=0,must-revalidate`,
Vary Accept. If-None-Match поддерживает weak W/,lists,*→304без тела.
nginx gzip добавляет Vary Accept-Encoding,ослабляет ETag; gzip chunked без
Content-Length,identity с длиной. Decoded bytes совпадают с исходным blob;
gzip уменьшает сеть, не распакованную память. Snapshot API — [SECTORS](SECTORS.md).

## API чтения/записи (Python)

`encode_binary_catalog_v2(items)`, `write_binary_catalog_v2(path,items)` atomic;
`read_binary_catalog(buffer)` dispatch v1/v2; `read_binary_catalog_v2(buffer)`;
`validate_catalog(items)` перед записью. JS декодирует strings батчем с переводом
byte→UTF-16 offsets; malformed/unusual layout использует построчный fallback.
Slices удерживают исходную строку до освобождения каталога.
Численные golden fixtures/команды — [tests/README](../tests/README.md).
