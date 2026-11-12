# Astroverse

Браузерный 3D-планетарий: React + Three.js, FastAPI, Docker.
Цель — все известные на дату обновления астрономические тела с проверяемыми
источниками и физическими положениями. Неизвестные параметры остаются null;
synthetic-нагрузки и иллюстративные орбиты не считаются измерениями.

## Текущее состояние

- `/`: Sun/Earth/Moon/Mercury/Venus, pinned DE440s, ICRF/SSB/km/TDB,
  UTC[2000-01-01,2027-06-28). Положение на requested time, UTC кадра/лаг в UI.
- 3471 справочная карточка: серверный поиск и bounded snapshot pages.
  Наличие карточки не подтверждает положение на дату.
- 6DoF, origin rebase, L0/L1/picking/refocus; камера не меняет физические центры.
- Opt-in [synthetic S-100k](docs/S100K.md):100000 центров через обычный physical
  manager/renderer/UI, один draw call; headless Metal stress принят при p95≤16.8ms.
  Реальный S-100k, monitor presentation, массовый streaming/LOD и поверхности открыты.
- `/?scene=legacy`: иллюстративные три вида, прежние LOD/меши/render-v2.

Целевая архитектура хранит и обновляет рабочие body/model данные в БД, без
обязательного полного objects.json. Сейчас default offline startup ещё
генерирует JSON и готовит runtime SQLite; published mode уже читает готовую БД
без каталожного JSON. Полная миграция и incremental3.7-B открыты — [ROADMAP](ROADMAP.md).
Прямой bounded SBDB import3.7-A реализован; пропуски не означают удаления.
Следующий этап — ограниченный incremental writer3.7-B для действующей SQLite:
локальные изменения карточек/индексов, согласованные ревизии и публикация.
Миграция обычного startup/offline на БД и расширение моделей — отдельные этапы.

## Запуск

Нужны Docker Compose и WebGL2.

```bash
docker compose up --build -d
# http://localhost:5173
docker compose down
```

Nginx проксирует `/api`, backend:8000 наружу закрыт. Настройки —
[.env.example](.env.example). Localhost:
`ASTROVERSE_BIND=127.0.0.1 docker compose up -d`; другой порт:
`ASTROVERSE_PORT=8080 docker compose up -d`. В LAN используйте IP машины;
публичный HTTPS требует TLS/защиты/наблюдаемости/backup restore из Фазы 9.
Логи: `docker compose logs -f backend frontend`.

## Управление

ЛКМ — вращение, колесо — zoom, ПКМ — панорама; touch — свайп/пинч.
Поиск/список/маркер выбирают карточку, «Наблюдать» возвращает к телу.
В свободном полёте: W/S вперёд/назад,A/D вбок,R/F вверх/вниз; стрелки —
поворот,Q/E — крен, мышь — поворот,+/− — скорость, пробел — стоп.
Нажмите на сцену для клавиатуры. Скорость относится к реальному времени RAF,
не к скорости симуляции. Выход из полёта сохраняет место камеры.
Пауза/«Сейчас»/±день/скорость/реверс доступны в topbar;
[контракт камеры](docs/NAVIGATION.md).

## Разработка и данные

```bash
cd frontend
npm ci
npm run dev
# Vite:5173, API proxy на127.0.0.1:8000
```

Docker modes: offline(по умолчанию),online,existing JSON,published SQLite через
`ASTROVERSE_SECTOR_PATH`. Online failure→offline fallback; неудачная подготовка
не заменяет прежний каталог. `catalog_seed.json` — численный/справочный fixture,
`catalog_config.json` — источники/лимиты; оба нужны. BSP и lockfiles сохраняются.

`data/catalog.py` — общий API; schema и бинарные codecs выделены в отдельные
модули. Physical manager отделён от проверки/сборки кадра (`sectorFrame.js`);
legacy LOD — от владения детальными мешами (`lodDetailedMeshes.js`).

| Документ | Назначение |
|---|---|
|[ROADMAP](ROADMAP.md)|Статус и порядок следующих этапов|
|[AGENTS](AGENTS.md)|Владельцы кода, ограничения и pitfalls|
|[COORDINATES](docs/COORDINATES.md),[HIERARCHY](docs/HIERARCHY.md)|Единицы, frame/time, unknown, requested-time physics|
|[SOURCES](docs/SOURCES.md),[SOURCE_AUDIT](docs/SOURCE_AUDIT.md)|Реестр и подтверждение источников|
|[SECTORS](docs/SECTORS.md)|SQLite, streaming/import, snapshot API и лимиты|
|[PHYSICAL_LOD](docs/PHYSICAL_LOD.md),[S100K](docs/S100K.md)|Renderer/LOD и synthetic acceptance|
|[BINARY_CATALOG](docs/BINARY_CATALOG.md)|Legacy JSON/v1/v2|
|[tests/README](tests/README.md),[TEST_COVERAGE](docs/TEST_COVERAGE.md)|Команды, методика и результаты|
|[HISTORY](docs/HISTORY.md)|Краткая история; полные старые отчёты доступны в Git|

CI проверяет backend/frontend coverage и build; WebGL отдельно через Chrome MCP.
Legacy CDN-текстуры не становятся автономными от offline-каталога; общий
frontend chunk>500kB остаётся известным предупреждением сборки.
