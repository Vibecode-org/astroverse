# Координатная иерархия

`data/physical_hierarchy.py` добавляет `physical-hierarchy/1` к `positions/1`;
`frontend/src/physical/hierarchy.js` проверяет граф, считает относительные векторы.
Трансляции sector→system→body: параллельные оси, без вращений.

## Контракт `physical-hierarchy/1`

| Поля | Значение |
|---|---|
|`version`, `revision`, `jd_tdb`, `evaluated_at`|Схема, ревизия и момент родительского ответа|
|`reference_system`, `origin`, `unit`, `time_scale`|ICRF, solar_system_barycenter, km, TDB|
|`sectors[]`|`id, origin_km` в канонической системе|
|`systems[]`|`id, sector_id, offset_km` относительно сектора|
|`bodies[]`|`id, system_id, offset_km` относительно системы|

Production: сектор `solar:verified`, система `solar:verified:ssb`; начала —
SSB `[0,0,0]`, опоры, не тела. Суффикс ревизии `hierarchy1-ssb1`;
ETag учитывает payload; `nearby` — manifest без body hierarchy.
Канонические `objects[].position`, пять центров/интервалы DE440s и source_epoch
не меняются. Неизвестные `system_id/offset_km/accuracy` — null.

## Проверки и преобразования frontend

Совпадают время/ревизия/frame; ID уникальны, родители существуют, body ID
соответствуют objects, векторы конечны. Лимиты decoder:128секторов/512систем/
4096тел, ID≤512символов; обычный HTTP ответ≤128центров/256KiB.
Корректный плоский `positions/1` поддержан; неверная явная hierarchy —
отказ без fallback. Snapshot/legacy не становятся requested-time physics.

По каждой оси `sector.origin + system.offset + body.offset` совпадает с canonical
в пределах `8×Number.EPSILON×max(1, сумма модулей слагаемых и canonical)`.
Null не превращается в ноль; overflow отвергается. Относительный вектор —
разность компонентов от ближайшего общего уровня до сложения больших начал.
Заданные sub-ULP offsets сохраняются; утраченная точность не восстанавливается.
GPU transform: `(X,Z,−Y)/100000`, km→render units; Float64 centers неизменны.

Допуски арифметики/камеры — [NAVIGATION](NAVIGATION.md); physical/source/time
контракт — [COORDINATES](COORDINATES.md). Общий временной индекс/массовая hierarchy
открыты; synthetic flat [S100K](S100K.md) не расширяет decoder4096.
Fixtures/проверки/команды — [tests/README](../tests/README.md).
