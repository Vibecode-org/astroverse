# Аудит источников

Seed **3471**, аудит 2026-11-06; не новая онлайн-выгрузка. Метки source
не подтверждают frame/эпоху/точность; ICRS/J2000 строкам не приписываются.

| Метка seed | Число | Пробел для положения на дату |
|---|---:|---|
| NASA Exoplanet Archive | 2733 | Направление/расстояние системы, без полной астрометрии и орбиты планеты |
| NASA JPL SBDB | 400 | a/per без элементов, эпохи и фазы |
| Messier / Caldwell | 110 / 109 | Нет первичной строки с frame/эпохой/ошибкой |
| NASA JPL Horizons | 80 | Нет сохранённого вектора с моментом/центром/frame |
| Нет source / NASA | 26 / 8 | Астрометрия не подтверждена |
| NASA / ESA; Event Horizon Telescope; NASA Chandra; EHT Collaboration; ESA Gaia | По 1 | Метки без первичных метаданных; Gaia без release/source_id/эпохи |

[NEA](https://exoplanetarchive.ipac.caltech.edu/docs/API_PS_columns.html): RA/Dec
системы deg→hours/deg, sy_dist pc→ly; нет полной астрометрии/ковариации/эпохи.
[SBDB units](../tests/fixtures/sbdb_field_units.json): a=AU, per=days, per_y=years,
epoch=JD TDB; запрос использует per, не полный набор элементов/эпоху.

## Подтверждённые эфемериды

Pinned [DE440s](../data/ephemeris/README.md): Sun 10, Earth 399, Moon 301,
Mercury 199, Venus 299; body-сегменты 1→199/2→299, не барицентры.
Geometric ICRF XYZ/SSB/km/TDB. Другие центры/движение каталога не подтверждены.

UTC: Skyfield 1.53 built-in leap table; [IERS C72](https://hpiers.obspm.fr/iers/bul/bulc/bulletinc.72)
исключает декабрьскую вставку 2026. [Таблица IERS](https://hpiers.obspm.fr/iers/bul/bulc/Leap_Second.dat),
проверенная 2026-11-09, истекает 2027-06-28: API UTC [2000-01-01, 2027-06-28),
JD TDB [2451544.5, 2462502.5). Факты/offsets:
[utc_leap_support.json](../tests/fixtures/utc_leap_support.json).

[100 Horizons-векторов](../tests/fixtures/horizons_centers.json), DE441,
20 дат/тело: ICRF, `500@0`, KM-S, TDB, `VEC_CORR=NONE`, `REF_PLANE=FRAME`.
Заголовки/параметры/значения сохранены; [тест](../tests/test_positions.py).
Максимальная 3D-разница DE440s↔DE441: **0.002420538 км**, допуск **1 км**;
Mercury **0.000002765 км**, Venus **0.000002098 км**.
Выборочная регрессия 2000–2027 не гарантирует ошибку всего интервала:
абсолютная `accuracy=null`.
Вращение/поверхности/наблюдатель/light-time/аберрация не входят в модель.
[Контракты](COORDINATES.md), [реестр и охват](SOURCES.md).
