# ROADMAP — Astroverse

2026-11-16. `[x]` проверено, `[~]` частично, `[ ]` открыто. Номера/статусы
сохранены; правка документации не означает приёмку.
Результаты — [TEST_COVERAGE](docs/TEST_COVERAGE.md), команды — [tests/README](tests/README.md).

## Цель и порядок

Все известные на дату обновления астрономические тела; coverage/gaps источников
учитываются. Миллион записей и S-100k — рубежи, не предел каталога. Рабочие
данные тел/моделей — в обновляемой БД; JSON допустим для API/fixtures/tooling.
Startup/offline SQLite и backup/restore приняты; общий body/model registry открыт.

Далее: общий временной индекс/массовый physical streaming3.3 и инфраструктурная
приёмка3.9/6 → расширение проверенных источников/моделей10.0.1/10.3/10.4 →
реальный S-100k → поверхности/релиз. Полёт/synthetic S-100k — параллельная
продуктовая ветка; новые тела не предпосылка инфраструктуры. Вне v1.0: VR,
моды, multiplayer, полная процедурная вселенная, редактор планет, N-body.

Для v1.0 нужны: Docker macOS/Linux/LAN без ручных шагов; найти→подлететь→
облететь→поверхность→галактика без перезагрузки/рывков; миллион записей без
полной стартовой загрузки; реальные положения/ориентации выбранной даты/Now;
аппаратные60+fps/1080p на M1/GTX1060,<50draw calls; HTTPS/security/health,
проверенные обновление/откат/backup БД+config+научных ресурсов.

**S-100k:** при открытии frontend видны100000 объектов, каждый интерактивен
(picking/search/card/refocus/time, включая перекрытия),60+fps. Synthetic и
реальная сцена — отдельная приёмка. Фиксировать cold-interactive latency,
resident/submitted/in-frustum,CPU/GPU/RAM/frame distributions/pauses и оборудование.
Headless Metal stress принят при пользовательском p95≤16.8ms вместо исходных
16.667ms; monitor presentation/аппаратные60+fps и реальный S-100k открыты.
[Профиль](docs/S100K.md), [измерения](docs/reports/s100k_report.json).

## Обязательные ограничения K-1…K-10

Points/InstancedMesh и единичные detail meshes; typed SoA core24–40B/объект
не равен full v2. Физика отделена от камеры/GPU: только линейные transforms,
без сжатия расстояний/раздвигания центров/ID-фаз. Unknown=null, synthetic явно отмечен.
ID-seed допустим для оформления. Shared ресурсы не мутируют, scene принадлежит appRef;
изменяемые global singletons запрещены. Приёмка численная+реальный
WebGL+пользовательский сценарий. Frame/origin/unit/epoch/time/source/accuracy
объявлены; рабочий каталог в БД, startup без полного objects.json.
[Физический контракт](docs/COORDINATES.md), [источники](docs/SOURCE_AUDIT.md).

## 0–2. Legacy-база

- [x] 0.1–0.7 Диагностика, иллюстративные орбиты, время/реверс, визуальная проверка/свет.
- [x] 1.1–1.13 L0/L1/L2,picking,hysteresis/dispose,shared resources,CPU LOD/WeakMap.
- [~] 2.1–2.9 Python/JS binary v1/v2,gzip/ETag/SQLite search проверены; full v2≈130MB/млн
  при цели≈30MB; нужны compact metadata/streaming, GPU-орбиты отложены.

## 3. Индекс и streaming `[~]`

- [x] 3.0 Snapshot/physics контракты раздельны; snapshot `at` всегда422.
- [x] 3.1 SQLite R-tree/grid/octree,parent families,frames/null.
- [x] 3.2 Bounded nearby/page/locate,snapshot pin/409,ETag; limits до304.
- [~] 3.3 Atomic multisector manager,time/revisions/cancel/retry/admission/coalescing
  проверен на ограниченном fixture. Добавлен ограниченный temporal SQLite slice:
  five-center conservative lane и synthetic affine swept-AABB→positions→residency;
  [контракт/бюджеты](docs/PHYSICAL_STREAMING.md). Общий временной индекс,
  массовые реальные положения и весь3.3 открыты.
- [~] 3.4 Ограниченные CPU/GPU budgets/cache/residency проверены; общий GPU manager открыт.
- [x] 3.5 DiskCatalog,streaming JSON→SQLite на seed/100k/1млн; старый online builder списочный.
- [x] 3.6 Separate sector/filtered caches8MiB,full BLOB chunks64KiB.
- [~] 3.7 A:bounded SBDB import/staging/manifest/atomic publication принят.
  Ограниченный B:local card/graph/search/cell updates,no-op/split/merge/old readers/
  concurrent writers/crash проверены. Copy/hash/integrity/legacy остаются O(N),
  full imports не локальный patch; весь B и общий body/model DB registry открыты.
  Pinned SQLite,offline volume lifecycle,явная migration,backup/restore
  приняты отдельно. [Контракт](docs/SECTORS.md), [lifecycle](docs/STARTUP.md).
- [~] 3.8 Ограниченные L0/L1,32detail/4096centers,128checks/RAF проверены;
  массовый LOD/L2/физические размеры открыты.
- [~] 3.9 Unit/HTTP/Chrome/numeric/отказы текущего этапа приняты; общая нагрузочная
  приёмка/deep-sky positions открыты.

## 4. Координатная иерархия `[~]`

- [ ] 4.1 Убрать physical-искажающее сжатие legacy `equatorialXYZ` при миграции.
- [~] 4.2 Sector→system→body/Float64/local deltas проверены для5centers/synthetic;
  полный каталог/галактика открыты.
- [ ] 4.3 Устранить причины53legacy-пересечений, сохраняя реальные сближения/проекции.
- [~] 4.4 Frame/origin/unit/time/transitions+100Horizons проверены для минимума;
  согласование остальных источников открыто. [HIERARCHY](docs/HIERARCHY.md).

## 5–6. Графика и нагрузка `[ ]`

5.1–5.4: black-hole lensing,Doppler,photon ring,jets после координатного/ресурсного
минимума. Четыре карточки не подтверждают положения/эффекты.
6.1–6.3: секторная выдача/pages/cache на миллионе,рост N/плотности/конкуренции;
фиксированные limits ограничивают ответы/RAM. Полные экспорты O(N);
snapshots и positions испытываются отдельно. Второй backend не строить.

[x] Ограниченная snapshot/API приёмка6.1–6.3 (2026-11-17):100k/1млн,
конкуренция1/4/16,18перезапусков,288384timed requests,два300s окна.
Лимиты/пагинация/revision/publication проверены. Исправлены filtered304 bypass,
frontend stale-cache/large-family cards,повторная сборка одинаковых cold pages
и повторный поиск (общий прежний8MiB cache,ключ с ревизией).
Прежние diagnostic p95 failures — в отчёте; новый max239.0ms≤500ms,
это не принятый SLA. Backend coverage/frontend tests/build/production+test
Docker/Chrome прошли. Новые substring queries — O(N); общий этап6
и массовый physical streaming открыты. [Отчёт](docs/reports/api_load_report.json).

## 7. Воспроизводимость `[~]`

- [~] 7.1 Import provenance/hashes/versions есть; общий lock источников открыт.
- [~] 7.2 Offline/published SQLite,pinned bootstrap+сохранение patches приняты;
  общая source/UI-lock схема открыта; получение данных не их эпоха.
- [x] 7.3 Schema/validation/backward compatibility.
- [x] 7.4 Backend/frontend/HTTP/numeric/Chrome regressions.
- [x] 7.5 package-lock/npm ci.
- [x] 7.6 CI coverage/build (backend≥95%,sectors100%); remote result подтверждать отдельно.
- [x] 7.7 Playwright stack3471/stack100k по фактическому health.

## 8. Полёт и непрерывный масштаб `[ ]`

- [~] 8.1 Ограниченный6DoF/selection/refocus на5centers/synthetic принят.
- [~] 8.2 Float64 origin/rebase/log depth минимум принят; галактический диапазон открыт.
- [ ] 8.3 Бесшовные physical L0↔L1↔L2.
- [ ] 8.4 Surface/terrain/normal maps/landing/horizon.
- [ ] 8.5 Atmosphere/shadows/eclipses/rings.
- [~] 8.6 Flight hints/speed/input isolation готовы; полный contextual UI/autocomplete открыт.
- [ ] 8.7 Аппаратные60+fps/1080p,S-100k.
- [ ] 8.8 Screenshot regressions ключевых сценариев.

## 9. Публичный деплой `[ ]`

Дата/масштаб не заданы. SQLite исходно; PostgreSQL по измеренной потребности.
Источники обновляет отдельный процесс; startup научные данные не скачивает.
9.1 TLS/VPS/domain;9.2 backend закрыт,наружу80/443;9.3 security/rate/body limits;
9.4 logs/metrics/alerts;9.5 zero-downtime update+rollback;9.6 backups DB/config;
9.7 tagged images CI/CD;9.8 restore DB/config/scientific versions на отдельном
окружении с согласованными периодичностью/допустимой потерей;9.9 separate
health/readiness,migration/data+app rollback/отказы зависимостей;9.10 pinned BSP/
resources и source freshness/import/solver/workers/disk/backup metrics.
Локальные SQLite backup/restore приняты; эксплуатационная фаза открыта.

## 10. Физическая достоверность `[~]`

- [~] 10.0 Позиционные контракты приняты; rotation/pole/elements/epochs/albedo
  требуют отдельной схемы/validation; выпущенный binary v2 layout не менять.
- [~] 10.0.1 Opt-in5centers/source registry и SBDB import приняты; общий дисковый
  реестр/aliases/source adapters/coverage/refresh открыты. Новый объект модели
  не должен требовать ID-ветки scene/solver; ambiguity остаётся unknown.
- [~] 10.1 UTC/TDB,pause/reverse/same-date return5centers приняты; общая ориентация,
  legacy time-state и ±100лет открыты. Состояние — функция времени без накопления.
- [ ] 10.2 IAU rotation/poles/tilt/retrograde без двойного учёта,синхронность/либрация;
  10.2.1 precession optional. Непроверенные численные ориентиры не defaults.
- [ ] 10.3 Kepler/elements+rates/full phase/orientation/epoch,body-center/barycenter,
  lunar node precession. Неполное экзопланетное решение не requested-time position.
- [~] 10.4 DE440s5centers offline приняты; остальные planet/moon/small-body models
  проходят независимые эталоны и собственные time/frame/accuracy bounds.
- [~] 10.5 Float64/floating origin/linear transforms5centers приняты; массовая
  hierarchy/LOD открыта. Проекции сохраняют направления из одной точки наблюдения.
- [ ] 10.6 Source-based luminosity/color/phase; отсутствие параметров остаётся null.
- [ ] 10.7 Shadow/eclipse/transit geometry, после отдельного расширения UTC.
- [ ] 10.8 Attributed offline textures30–50bodies,physical albedo,verified shapes;
  подтверждённые карты нынешних экзопланет/звёзд не предполагаются.
- [~] 10.9 100Horizons vectors/numeric/HTTP/Chrome5centers приняты;
  orientation/events/other-source validation и прозрачная accuracy открыты.

Будущая приёмка (не выполнена): Horizons planets≤1″/Moon≤5″ на1900–2100,
20дат/согласованный observer; meridians Earth/Mars/Jupiter≤0.5° на2026-10-31;
retrograde Venus/Uranus, lunar synchronous/±7.9°libration,node18.6y/inclination5.145°;
Mercury/Pluto eccentricity0.206/0.249,датированный Earth–Moon barycenter;
±100лет→та же дата без дрейфа;Venus phase≤1° на2026-10-31;
eclipse2027-08-02/Mercury transit2032-11-13 после time extension;
100stars colorΔT≤200K;идеализированная BH photon sphere1.5r_s/shadow2.6r_s;
offline resources и отсутствие random physics. Допуски не равны абсолютной точности DE440.

Positions/1 geometric `NONE`; observable LT/aberration/light deflection требуют
отдельного контракта, не объявляются невидимыми. Координатный минимум4/10.0/10.5
предшествует новым моделям;10.6–10.8 согласуются с8.4/8.5. N-body/столкновения/
приливы/тектоника и прочая relativistic physics вне текущего объёма.
