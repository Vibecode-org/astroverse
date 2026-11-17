# Координаты и время

Реальные тела занимают настоящие положения выбранной даты; Now — текущий момент.
Frame/origin/unit/axes, эпоха, время, source/model/revision и accuracy — явные;
неизвестное — `null`. Метка источника/дата загрузки не задают эпоху.
Период/радиус не задают фазу орбиты. Камера/LOD/floating origin сохраняют центры
и расстояния линейно; маркеры/визуальные размеры — не измерения.

| Контракт | Семантика |
|---|---|
| `coordinates/1`, `/api/spatial/v1` | Каталожный снимок, только справочные карточки |
| `positions/1`, `/api/positions/v1`, сцена `/` | Центры на запрошенный момент |
| Legacy v2, `/?scene=legacy` | Иллюстративные render-координаты |

Контракты не взаимозаменяемы. Legacy live-ephemeris на начало суток не даёт Now.

## Каталожные снимки `coordinates/1`

| Поле | Значение |
|---|---|
| representation/unit | `catalog_snapshot` / ly = 9 460 730 472 580 800 м |
| Оси | x=d cos(lat) cos(lon), y=d sin(lat), z=d cos(lat) sin(lon); левая тройка, Y вверх |
| Углы | RA часы×15°, Dec градусы; Galactic l/b градусы; полная RA/Dec приоритетнее |
| reference_system/origin/source_epoch/time_scale/evaluated_at/accuracy | `null` |
| source | Исходная метка/null; общий контракт null (смешанные источники) |
| status | `unverified` с позицией корня; `unknown` без неё; `synthetic` при source=synthetic |
| position/simulation_position | Проекция корня, для потомков/solar null / всегда null |

`equatorial`/`galactic` — поля, не подтверждённый frame; преобразований между
ними нет. Направление хозяина не задаёт центр планеты. Измеренный 0 сохраняется,
отсутствие — не ноль. gx/gy/gz не физика. Любой `at` → **422
unsupported_simulation_time**, без экстраполяции. [ERFA t_s2c](https://github.com/liberfa/erfa/blob/master/src/t_erfa_c.c)
проверяет проекцию с Y/Z-перестановкой, допуск 1e-12: геометрия, не эфемерида.
[Разбиение](SECTORS.md).

## Положения на дату `positions/1`

| Свойство | Значение |
|---|---|
| Состав | Sun 10, Earth 399, Moon 301, Mercury 199, Venus 299; [opt-in](SOURCES.md), без подмены барицентрами 1/2/3 |
| representation/position_type/corrections | `simulation_position` / `geometric_center` / `NONE` |
| frame/axes/origin | ICRF / native right-handed XYZ / solar_system_barycenter |
| unit/time_scale/source | km / TDB / offline NASA/JPL DE440s, [pinned BSP](../data/ephemeris/README.md) |
| source_epoch/accuracy | null: единой эпохи и per-vector абсолютной неопределённости нет |
| evaluated_at/jd_tdb | UTC запроса; при явном JD TDB evaluated_at=null, момент задаёт jd_tdb |
| UTC | [2000-01-01T00:00:00Z, 2027-06-28T00:00:00Z), Skyfield 1.53 built-in leap table, IERS C72/table expiry |
| JD TDB | [2451544.5, 2462502.5), верхние границы исключены |
| Неизвестное тело | status=unknown, position=null, reason=no_verified_ephemeris |

[Horizons и UTC evidence](SOURCE_AUDIT.md): допуск регрессии не accuracy.
Маршруты `/api/positions/v1/{contract,sectors/solar:verified,objects/{id},nearby}`.
Ровно одно `at`/`jd_tdb`; UTC с T/timezone, секунда 60 не поддержана.
Неверная дата →422, недоступный/изменённый BSP →503, без snapshot/старой даты.
`nearby`: поддержанный anchor, конечные dx/dy/dz km ±1e13, radius 0…1e13;
ox/oy/oz вместе задают фиксированный ICRF/SSB origin km ±1e13, иначе origin=anchor
на дату. AABB на дату, production ответ 0/1 сектор без карточек; ≤128 центров/256 KiB,
превышение →413. Ограниченный [temporal index](PHYSICAL_STREAMING.md) хранит
все пять центров как безусловных кандидатов; общего массового индекса нет.

`revision` ≤256 закрепляет positions revision (не registry SHA);
`temporal_revision` ≤256 отдельно закрепляет публикацию индекса между nearby
и sectors/objects, frontend передаёт обе. Конфликт →409
position_revision_changed/no-store до If-None-Match. ETag учитывает время/ревизию/
содержимое; 304 без тела. LRU 1 MiB без BSP/NumPy. Четыре solver-слота, без очереди,
deadline 8 с; 503 busy/timeout, Retry-After:1/no-store; native слот занят до возврата.

CPU Float64; GPU `(X-originX, Z-originZ, -(Y-originY)) / 100000`, с отдельным Float32
округлением. Rebase меняет представление, не центры/камеру. Manifest/sector совпадают
по revision/registry_revision/sectorID/UTC/JD TDB; повтор всей выборки один раз.
Continuous: один запрос и последняя дата, время кадра/lag, без интерполяции.
Смена контекста исключает старый кадр/поздние ответы; ошибка не подменяет дату. [Иерархия](HIERARCHY.md), [навигация](NAVIGATION.md),
[LOD](PHYSICAL_LOD.md). Production — пять центров; [S-100k](S100K.md) synthetic.
`au` — а.е., `period_days` — сутки, `pl_eqt` — равновесная температура.

## Приближённые поверхности пяти тел

`physical/bodyModel.js` закрепляет числовое подмножество
[NAIF pck00011 (2022-12-27)](https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc).
Сферический радиус — среднее трёх PCK-полуосей, km: Sun 695700,
Earth 6371.0083667, Moon 1737.4, Mercury 2439.7733333, Venus 6051.8.
Гладкие сферы без рельефа/сплюснутости; неизвестным ID модель не назначается.
Радиусы и ориентация не меняют эфемеридные центры.

RA/Dec полюса и W меридиана вычисляются по полиномиальным членам PCK:
`d=jd_tdb−2451545`, `T=d/36525`. Вращение — по принятому кадру,
не времени RAF; скорость W Venus отрицательна. Периодические члены
Moon/Mercury опущены: лунная либрация не моделируется, возможна ошибка ориентации
в несколько градусов. Earth использует приблизительную IAU_EARTH,
без EOP/UT1, нутации и полярного движения; NAIF предупреждает об ошибке
меридиана ≥150 угловых секунд. Sun — условное твёрдое вращение без
дифференциальной ротации. Абсолютная accuracy упрощений null; точность DE440 не
переносится на поверхности, картографическая/навигационная точность не заявляется.

Локальные оси сферы: +Y северный полюс, +X нулевой меридиан на экваторе,
−Z долгота 90°E. После ориентации в ICRF применяется `(X,Z,−Y)`.
THREE SphereGeometry: u=.5 — 0°, u=.75 — 90°E, v=1 — север;
карта: север сверху, восточные долготы вправо. Геометрическое освещение:
от центра тела к центру Sun того же кадра, затем поворот в render;
без light-time, аберрации, затмений и фотометрической модели.
