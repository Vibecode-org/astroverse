# Astroverse

Браузерный 3D-планетарий: React + Three.js, FastAPI, Docker. Цель — свободный
полёт от галактики до поверхности, непрерывный масштаб и проверяемая астрометрия.
Долгосрочная цель — отразить все известные на дату обновления астрономические
тела с проверяемым происхождением данных. Полнота охвата определяется по источникам
и типам тел; неизвестные параметры и положения остаются неизвестными.

Все рабочие данные о телах и моделях в итоговой архитектуре хранятся и обновляются
в БД. Проект не использует фиксированные JSON-файлы как основной каталог тел
и не требует полного `objects.json` для запуска. JSON допустим для ответов API,
тестовых примеров и служебных файлов. Переход штатного запуска на эту архитектуру
ещё не завершён; [план миграции](ROADMAP.md).

Минимальный 6DoF на пяти центрах реализован; поверхности/массовый physical
streaming и полный галактический полёт ещё открыты; [план](ROADMAP.md).
Промежуточный **S-100k**: frontend отображает 100 000 объектов с взаимодействием
с каждым и 60+ fps; сначала synthetic, реальная сцена принимается отдельно.

## Сейчас

- `/`: Sun/Earth/Moon/Mercury/Venus, offline DE440s, ICRF/SSB/km/TDB,
  UTC **[2000-01-01, 2027-06-28)**, состав/маркеры из реестра. Положение на
  запрошенный момент; continuous показывает UTC кадра/лаг, unknown=null,
  неподдержанная дата — ошибка. Камера/масштаб сохраняют центры.
- **3471** справочная карточка: серверный поиск/bounded snapshot-страницы;
  карточка не подтверждает положение на дату.
- `/?scene=legacy`: иллюстративные три вида, сжатие/ID-орбиты, детальные меши,
  legacy LOD/render-v2; физическим форматом он не является.
- Проверены минимум координат/реестра, многосекторный менеджер и L0/L1 на
  32 synthetic секторах/2048 записях. Ограниченный прямой SBDB import 3.7-A
  проверен; полные incremental updates 3.7-B и S-100k ещё открыты.

- Opt-in [synthetic S-100k](docs/S100K.md): 100000 центров из SQLite через тот же
  physical manager/renderer, поиск/карточка/refocus/полёт; один Points draw.
  Функциональность проверена. Аппаратный критерий и полный рубеж ещё открыты;
  профиль не добавляет измеренных тел в production.

## Запуск

Нужны Docker Compose и браузер с WebGL2.

```bash
docker compose up --build -d
# http://localhost:5173
docker compose down
```

Логи: `docker compose logs -f backend frontend`. :8000 наружу закрыт,
frontend/nginx проксирует `/api`. LAN: `http://<IP-компьютера>:5173`, одна сеть,
разрешённый firewall; IP: macOS `ipconfig getifaddr en0`, Linux `hostname -I`.
Localhost: `ASTROVERSE_BIND=127.0.0.1 docker compose up -d`; другой порт:
`ASTROVERSE_PORT=8080 docker compose up -d`. Настройки — [.env.example](.env.example).
Публичный HTTPS требует Фазы 9 (TLS/защита/наблюдаемость/обновление/откат).

## Управление и разработка

Левая кнопка — вращение, колесо — zoom, правая — панорама; touch — свайп/пинч.
Выбор маркером/списком, повторный refocus; обзор, поиск/карточки, пауза,
«Сейчас», ±день, скорость/реверс. Обзор/окрестность — настройки камеры,
не границы будущего полёта.

«Свободный полёт»: W/S вперёд/назад, A/D вбок, R/F вверх/вниз; стрелки —
поворот, Q/E — крен, перетаскивание мышью — поворот. +/− меняют скорость,
пробел останавливает. Скорость в км/с относится к реальному времени кадра.
Нажмите на сцену для клавиатурного управления. Выбор в полёте открывает карточку;
«Наблюдать имя» возвращает к телу и следует за ним. Выход из полёта сохраняет
место камеры. Подсказка есть в UI; [подробный контракт](docs/NAVIGATION.md).

В текущем переходном пути `data/objects.json` создаётся при старте, не хранится в Git. `data/catalog_seed.json` — справочный
снимок (Messier/Caldwell ещё требуют сверки), `data/catalog_config.json` задаёт источники/лимиты.
Режим `ASTROVERSE_CATALOG_MODE`: offline по умолчанию, online NASA/JPL,
existing валидирует готовый JSON. Режим published открывает готовую SQLite
через `ASTROVERSE_SECTOR_PATH`, без каталожного JSON. Online-отказ → offline fallback;
неудачная offline-подготовка запрещает API, прежний каталог сохраняется.

```bash
# Ручная offline-сборка на хост; для online убрать --offline
docker compose run --rm --no-deps -e PYTHONDONTWRITEBYTECODE=1 \
  -v ./data:/app/data backend python /app/data/build_catalog.py --offline

# Локальный frontend: Vite :5173, proxy API на 127.0.0.1:8000
cd frontend
npm ci
npm run dev
```

Единицы/null и разграничение измерений/оформления — [COORDINATES](docs/COORDINATES.md).
Код: `frontend/src/physical/` — physical, `frontend/src/scene/` и `frontend/src/bodies/` — legacy;
`data/runtime_catalog.py` — чтение БД; остальные владельцы/правила — [AGENTS](AGENTS.md).
API: `/api/health`,
`/api/search`, `/api/objects/{id}`; [sources/1](docs/SOURCES.md),
[positions/1](docs/COORDINATES.md), [spatial/1](docs/SECTORS.md),
[legacy JSON/v1/v2](docs/BINARY_CATALOG.md). Legacy `/api/live-ephemeris`
физическим режимом не используется и Now не обеспечивает.

Проверки/benchmark — [tests/README](tests/README.md), актуальные результаты —
[TEST_COVERAGE](docs/TEST_COVERAGE.md), старые — [HISTORY](docs/HISTORY.md) и
[legacy GPU](docs/PERFORMANCE.md); источники — [SOURCE_AUDIT](docs/SOURCE_AUDIT.md).
CI: coverage/backend/frontend/build; настоящий WebGL отдельно через Chrome MCP.
Открыты временной индекс, массовый physical streaming/LOD, остальные реальные
тела/вращение/поверхности/полный полёт. Нынешние 100k/миллион — synthetic-нагрузки.
Legacy CDN-текстуры не автономны с offline-каталогом; крупные synthetic-меши
перекрываются; build предупреждает о chunk >500 kB. Пять центров это не закрывают.


Ограниченный этап synthetic S-100k update: validation/merge и flat decode
разбиты на отменяемые порции; typed bitmap/прямое Float32 преобразование
уменьшают allocations. Чистые динамические окна и аппаратный Metal headless
прогон — [S100K](docs/S100K.md), [машинный отчёт](docs/s100k_report.json).
Frame p9516.8ms согласован пользователем2026-11-12; полный S-100k остаётся
открыт. Это не
завершение массового physical streaming, 3.7-B или Фазы 8.
