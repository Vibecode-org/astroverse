# Ограниченный temporal physical streaming

Отдельный immutable SQLite-индекс выбирает области на запрошенный момент;
sector-запрос вычисляет их центры на тот же момент. Slice не закрывает общий
temporal index, массовую physical hierarchy, полноту каталога или hardware
S-100k. Ограничения [координат/времени](COORDINATES.md), [иерархии](HIERARCHY.md)
и [CPU/GPU admission](PHYSICAL_LOD.md) сохраняются.

## Два набора данных

Production: пять разрешённых DE440s body centers — Sun 10, Earth 399, Moon 301,
Mercury 199, Venus 299. Консервативный кандидат — весь `solar:verified` на всём
интервале модели, без исключения по snapshot, приблизительной орбите, выборочным
датам или выдуманной внешней границе. После admission вычисляются пять центров
на дату и пересечение sphere с текущим AABB. Ступень полная, пространственно
неселективная; ускорение solver не обещано. Новых тел, моделей, интервалов
UTC/TDB и загрузок эфемерид нет.

Отдельная opt-in synthetic fixture задаёт искусственную affine функцию:

`position_km(jd_tdb) = position_at_epoch_km + velocity_km_per_day × (jd_tdb − epoch_jd_tdb)`.

Это тест, не измерение, экстраполяция реального тела или неявная орбита.
Профиль/источник/ответы помечены synthetic; индекс и registry не меняют
production. Скорость — km/TDB day, не km/s. Неизвестная траектория:
`position=null`, без границы и подстановки начала координат. Полный sector
payload сохраняет неизвестные null-записи.

## Полнота выбора

Конечный bucket (обычный generator: 365 TDB days) хранит swept AABB известных
членов области. Affine координата линейна: минимум/максимум достигаются на
концах bucket. Огибающая включает оба конца, выбор bucket — `[start, stop)`;
seam не создаёт пропуска, исключённый конец модели не становится допустимой датой.

SQLite/Rtree broad phase допускает лишних кандидатов, но не пропуск области
с центром внутри query sphere на дату. Snapshot AABB для движущихся центров
запрещён. Synthetic nearby пересекает охватывающий sphere query cube со swept
AABB, без узкого теста текущих центров; sector-запрос вычисляет их на дату.
Production nearby дополнительно проверяет sphere против текущего AABB пяти
центров, включая касание `distance <= radius`. Payload содержит всю область,
включая центры вне sphere; пересечение AABB не гарантирует центра внутри sphere.

Фиксированный `ox/oy/oz` (только все три вместе) задаёт ICRF/SSB origin;
query center = origin + `dx/dy/dz`, независимо от anchor. Иначе origin —
положение поддержанного anchor на дату. Admission предшествует решению
выбранных областей; вычисление anchor может предшествовать пространственному
поиску. Dense overflow без solver проверяется с фиксированным origin.

## Время, идентичность и атомарный кадр

`positions/1`: requested-time geometric centers, ICRF/native XYZ,
solar-system barycenter, km, TDB, corrections NONE. Production UTC:
`[2000-01-01T00:00:00Z, 2027-06-28T00:00:00Z)`; JD TDB:
`[2451544.5, 2462502.5)`. Ровно одно `at`/`jd_tdb`; вне интервала — 422 без
snapshot, предыдущей даты или частичного кадра. Вход TDB: `evaluated_at=null`,
момент — `jd_tdb`. Production `source_epoch` и абсолютная `accuracy` — null;
synthetic `source_epoch` задаёт epoch affine функции. Numerical regression
tolerance не заменяет accuracy.

Индекс связан с model/source, registry revision и publication revision.
Запрос/manifest/sector payload совпадают по этим идентичностям, frame и точному
принятому времени. Immutable index не перезаписывается под активным reader.
Конфликт revision — 409/no-store и полный discovery заново; ETag, включая `*`,
не обходят проверку revision/даты/query. Часть кадра с другой датой/ревизией
не принимается.

`temporal_revision` закрепляет индекс между discovery и sector reads;
frontend передаёт её вместе с positions revision. Ревизия snapshot-карточек
отдельна: изменение описания не меняет физическую модель. Индекс пяти центров
создаётся детерминированно без полного каталога/JSON; membership и модель
закреплены существующим registry/BSP contract.

Frontend: один целый displayed frame и ограниченный staged frame. Камера/дата/
контекст инвалидируют устаревшую выборку; отменённый/поздний ответ не меняет
центры, accepted timestamp или picking. Пустой успех очищает область; ошибка
не становится успешным пустым/частичным кадром. Now сохраняет coalescing;
шаги вперёд/назад используют время, без интеграции предыдущих координат.
Floating origin/LOD сохраняют центры линейно.

## Обязательные пределы и диагностика

Обязательные лимиты slice: 128 записей/256 KiB на область, 16 областей/2048
записей на новую выборку; старый + новый набор укладываются в decoder4096 и
его memory admission. Dense overflow — 413 до решения выбранных областей.
Более 16 swept-кандидатов могут дать 413 даже при меньшей точной текущей
выборке: требуется уменьшить radius. Бесконечная очередь, неограниченный ответ
и тихое усечение запрещены. [PositionWork](../backend/position_work.py):
четыре solver-слота без backlog, deadline 8 s; native timeout удерживает слот
до фактического возврата.

Диагностические цели зафиксированы **до измерений**; это не доказательство
hardware 60 fps:

| Метрика | p95 | p99 / предел |
|---|---:|---:|
| Server selection | 100 ms | 250 ms |
| Server positions | 250 ms | 500 ms |
| Request → accepted frame | 500 ms | 1500 ms |
| Browser CPU frame | 16.8 ms | p99 записывается без заданного порога |
| Backend RSS | — | 512 MiB; late-window growth ≤32 MiB |

В замерах: объём fixture, число известных/null тел и кандидатов/выбранных областей,
workload, renderer, длительность/число циклов, ошибки/отмены, sample count,
RSS windows. Software renderer — функциональное свидетельство; CPU frame timing
не GPU timing. Отчёт отдельно показывает соблюдение лимитов и попадание
в диагностические цели.

## Независимые численные проверки

Affine oracle считает центры из исходных `p0`, velocity и JD без чтения
AABB/selector. Полная oracle-выборка на каждую дату сравнивается с broad-phase
кандидатами и accepted payload: crossing, вход/выход, касание, bucket seam,
обратное время, фиксированный origin, null без нулевой подстановки.
Перестановка ID/порядка ответов не меняет физическое множество.

Production: 100 сохранённых независимых Horizons vectors для пяти body centers;
допуск — numerical regression DE440s против reference DE441. HTTP/browser
дополняют численную проверку; screenshot её не заменяет. Команды/фактические
проверки — в [tests/README](../tests/README.md) и отчёте спринта.
