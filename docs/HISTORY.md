# История существенных изменений

Актуальные контракты — в документах архитектуры, состояние — в
[ROADMAP](../ROADMAP.md), результаты — в [TEST_COVERAGE](TEST_COVERAGE.md).
Числа ниже относятся к указанным прогонам, не к каждому последующему изменению.
Полные первоначальные отчёты сохранены в Git на
[ревизии 7f66098](https://github.com/Vibecode-org/astroverse/tree/7f6609842f10e9cbfc5516f6193d9e22e4e3d54f/docs).
Их ссылки вида `git:revision:path` в сводных JSON — архивные адреса, не локальные файлы.

## Legacy и бинарный каталог

Исправлены совпадавшие иллюстративные орбиты экзопланет, добавлены L0/L1/L2,
виртуализация списка, shared GPU resources, бинарные v1/v2 и gzip/ETag.
Legacy-замер 2026-11-02: synthetic100k, headed Chrome/ANGLE Metal/M1 Pro,
1440×1000, RAF3s после прогрева, медиана трёх прогонов. Draw calls245→44,
треугольники 35.48→4.08 млн, fps11.8→~39 (пауза~46), heap245→252–268MB.
Это историческая legacy-приёмка, не physical S-100k и не доказательство 60fps.
V2:13000172B raw/2456590B gzip, parse122–164ms; HTTP304 не передаёт тело.
Формат и действующие ограничения — [BINARY_CATALOG](BINARY_CATALOG.md).

## Проверка офлайн-индекса

SQLite/R-tree проверены против независимого перебора, с unknown/null,
разными frame, переполнениями, parent closure, split/merge и атомарной заменой.
Runtime DiskCatalog заменил полный список в production. JSON→SQLite и patches
ограничены по RAM; финальная публикация legacy/графа пока остаётся O(N).
Million-row и S-100k — рубежи проверки, не предел каталога и не полнота источников.

## Проверенные положения и ограниченный streaming

Добавлены positions/1, реестр пяти геометрических центров и DE440s с pinned
SHA-256; snapshots не подаются в physical scene. Все 100 независимых
Horizons/DE441 векторов проходят: max0.002420538km при регрессионном допуске 1km;
клиентские преобразования — <1e-6km. Это не абсолютная неопределённость.
UTC продлён до[2000-01-01,2027-06-28) по IERS C72/table expiry.

physical-hierarchy/1 сохраняет локальные sub-ULP offsets при большом общем
начале. Добавлены согласованный многосекторный manager, retry409, cancellation,
worker drain и memory admission. Continuous coalescing завершает текущий запрос,
затем берёт последнее desired время; UI показывает UTC принятого кадра и лаг.
Нативный solver после HTTP deadline сохраняет слот до фактического завершения.
32×64 HTTP fixture проверил 2016 computed/32 unknown, ошибки, timeout и 48 циклов
load/evict/return. Пределы/измерения — [physical_budget_report.json](physical_budget_report.json).
Массовый временной индекс, streaming и L2 этим не закрыты.

## Прямой SBDB import 3.7-A, 2026-11-10

SBDB HTTP→bounded raw SQLite→нормализация/валидация→atomic runtime revision.
Paging/resume не вводились: SBDB не закрепляет ревизию между страницами.
Пропуски не удаляют записи; удаления только explicit owned IDs. Старые readers,
конкурирующие writers, SIGKILL/restart, отказ validate/rename/cleanup проверены.
Redirect запрещён до чтения тела; token/nesting/bytes ограничены до ijson.
Generator и JSON используют общий validate_record, прежние ID/visual overrides
сохраняются, неоднозначная legacy identity отклоняется.

Live-проверка официального SBDB Query API1.0: fields=full_name,pdes,a,per,diameter;
sb-kind=a,sort=pdes,limit=3; returned3/matching1580093,345B, SHA-256
`ace6ecf2c0d00382b011265383cd54363b45074c095f74d2268fef87e6aca243`.
Ответ динамический, не архивировался; детерминированная приёмка использует
synthetic HTTP fixture. Это проверка адаптера, не реальных requested-time positions.

100k/1 млн:12.29/130.19s, RSS55.76/55.69MiB; бюджеты пройдены.
[Методика и фазы](import_budget_report.json). Published startup читает SQLite
без полного objects.json; штатный offline startup ещё переходный.
3.7-B, распределённые writers, power-loss durability и полная миграция открыты.

## Навигация, depth и picking

Добавлены 6DoF, фиксированная physical-опора, линейный rebase и сохранение
камеры при выходе из полёта/полюсах. Исправлены shader log-depth, выбор
переднего совпавшего центра и drag suppression. WebGL readPixels проверяет
L0/L1, оба порядка и 1e7…1e12km; screenshots не заменяют численные проверки.

Удалено дистанционное скрытие resident/computed центров внутри принятого кадра.
У Земли submitted все пять центров. Вход в полёт после удаления от Меркурия
>200 млнkm сохраняет камеру и область загрузки. Три повторных цикла дают
нулевой physical jump при допуске 1e-6km, без роста ресурсов.

Camera outliers9.3ms и 11ms сохранены в
[navigation_budget_report.json](navigation_budget_report.json), порог 8ms не
повышался. Последний повтор: camera p95/max0.1/1.0ms, apply0.2/1.5ms,
LOD0.1/0.4ms;12 циклов стабильны. Причина старых outliers не объявлена исправленной.

## Synthetic S-100k и динамическая приёмка,2026-11-12

Opt-in SQLite/HTTP профиль 100×1000 использует тот же physical manager/renderer/UI.
Полные merge/global validation и flat filtering заменены отменяемыми порциями;
typed bitmap и прямое Float32-преобразование уменьшают allocations.
Слишком частые scheduler continuations ухудшали continuous frame-time.
Общая квота 2ms между RAF устранила эту регрессию; timeout32ms позволяет
освободить staging скрытой вкладки. Commit остаётся атомарным.

Первоначальный frame p95≤16.667ms не пройден. Пользователь явно согласовал
≤16.8ms; старые измерения/порог сохранены, остальные бюджеты не менялись.
Metal baseline reverse p99/max83.3/316.7ms; итоговый stress16.8/16.8ms.
12 циклов/19 окон/11475RAF samples: пауз>50ms0, cold3.298s,
100000 submitted/in-frustum,1draw call, стабильные ресурсы. Это headless Metal,
не monitor presentation/реальный S-100k/вся Фаза 8.

Неполный прогон остановился после 9 циклов при закрытии Chrome/прерывании сеанса;
затем fixture был обнаружен штатно остановленным. Эти попытки не считаются PASS.
Повтор на восстановленном fixture завершился; health проверяется до Chrome.
Raw evidence, hashes, baseline/стресс и ограничения объединены в
[s100k_report.json](s100k_report.json). До очистки backend242/frontend222,
coverage/build,100Horizons и финальные navigation/depth проверки прошли;
[GitHub CI7f66098](https://github.com/Vibecode-org/astroverse/actions/runs/43280190293) — success.

## Очистка репозитория

Промпт следующего сеанса удалён. Дубли отчётов объединены в четыре тематических
JSON без округления измерений; полные старые версии доступны в Git.
Удалены одноразовые probes, их полезные timing/picking измерения включены в
существующий physical benchmark. Убраны подтверждённые неиспользуемые импорты,
генерируемые build/coverage/cache файлы. Runtime-контракты, сценарии проверок,
численные fixtures, BSP, конфигурации и lockfiles сохранены.
