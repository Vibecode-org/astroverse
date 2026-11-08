# Astroverse

Браузерный 3D-планетарий (React + Three.js, FastAPI, Docker). Цель — свободный
полёт в едином пространстве от галактики до поверхности, непрерывный масштаб
и проверяемые астрономические данные. Полёт, поверхности и массовый физический
стриминг ещё не реализованы; порядок работ — [ROADMAP.md](ROADMAP.md).

## Текущее состояние

- `/` — физическая сцена пяти центров: Солнце, Земля, Луна, Меркурий, Венера.
  Offline JPL DE440s, ICRF/SSB/km/TDB; UTC **2000–2026**. Состав и маркеры
  поступают из единого реестра. Камера и масштаб сохраняют физические центры.
- Положения вычисляются на запрошенный момент. В непрерывном режиме интерфейс
  отдельно показывает UTC принятого кадра и отставание от часов симуляции.
  Неподдержанная дата даёт ошибку, неизвестное положение остаётся `null`.
- Каталог из **3471** справочной карточки доступен через серверный поиск и
  ограниченные snapshot-страницы. Карточка не подтверждает положение на дату.
- `/?scene=legacy` — иллюстративный интерфейс: три вида, сжатые расстояния,
  круговые орбиты/фазы от ID, детальные меши и legacy LOD. Его render-v2
  не является физическим форматом.
- Проверены координатный минимум 4.2/4.4/10.5 и ограниченная часть 10.0.1.
  Следующий шаг — **3.3, общий менеджер секторов**, затем 3.8/3.4 с приёмкой 3.9.

Требование всех реальных тел на настоящих местах и контракты:
[COORDINATES](docs/COORDINATES.md). Источники и ограничения:
[SOURCE_AUDIT](docs/SOURCE_AUDIT.md), [SOURCES](docs/SOURCES.md).

## Запуск

Нужны Docker с Compose и браузер с WebGL2.

```bash
docker compose up --build -d
# http://localhost:5173
docker compose down
```

Логи: `docker compose logs -f backend frontend`. Backend-порт 8000 наружу
не опубликован; frontend/nginx проксирует `/api`.

LAN: `http://<IP-компьютера>:5173` (одна сеть, firewall разрешает порт).
IP: `ipconfig getifaddr en0` на macOS, `hostname -I` на Linux.
Только localhost: `ASTROVERSE_BIND=127.0.0.1 docker compose up -d`.
Другой порт: `ASTROVERSE_PORT=8080 docker compose up -d`.
Настройки — [.env.example](.env.example). Публичный HTTPS-деплой требует Фазы 9:
TLS, защиты, наблюдаемости и проверенного обновления/отката.

## Управление

Мышь: левая кнопка — вращение, колесо — приближение, правая — панорама.
На touch — свайп/пинч. Выбор — маркер или список; повторное наведение — refocus.
Есть обзор, поиск/карточки, пауза, «Сейчас», ±день, скорость и обратное время.
Обзор и окрестность тела — текущие настройки камеры, не границы будущего полёта.

## Каталог и разработка

`data/objects.json` создаётся при старте и не хранится в Git.
`data/catalog_seed.json` — офлайн-снимок справочных данных; Messier/Caldwell
требуют научной сверки. `catalog_config.json` задаёт источники и лимиты.
Неизвестные измерения — `null`; RA — часы, Dec — градусы, distance — ly,
`au` — а.е., `period_days` — сутки. `pl_eqt` — равновесная температура;
визуальные radius/color/texture не считаются измерениями.

`ASTROVERSE_CATALOG_MODE`: `offline` (по умолчанию), `online` (NASA/JPL),
`existing` (валидация готового JSON). Online-отказ запускает offline fallback;
ошибка offline-подготовки запрещает запуск API, прежний каталог сохраняется.

```bash
# Ручная offline-сборка на хост; для online убрать --offline
docker compose run --rm --no-deps -e PYTHONDONTWRITEBYTECODE=1 \
  -v ./data:/app/data backend python /app/data/build_catalog.py --offline

# Локальный frontend: Vite :5173, proxy API на 127.0.0.1:8000
cd frontend
npm ci
npm run dev
```

Основные модули: `frontend/src/physical/` — физическая сцена,
`src/scene/` и `src/bodies/` — legacy; `backend/app.py` — приложение,
`position_api.py` — положения, `sector_api.py` — снимки;
`data/source_registry.py`, `ephemeris.py`, `physical_hierarchy.py` — физические
контракты; `streaming_catalog.py`, `runtime_catalog.py`, `incremental_catalog.py`
— дисковая подготовка/чтение/патчи. BSP — сохраняемый исходный актив.

API: `/api/health`, `/api/search`, `/api/objects/{id}`;
[sources/1](docs/SOURCES.md), [positions/1](docs/COORDINATES.md),
[spatial/1](docs/SECTORS.md), [legacy JSON/v1/v2](docs/BINARY_CATALOG.md).
Legacy `/api/live-ephemeris` не используется физической сценой и не обеспечивает Now.

## Проверки и ограничения

Команды — [tests/README.md](tests/README.md), последние результаты и измерения —
[TEST_COVERAGE](docs/TEST_COVERAGE.md). CI проверяет backend/frontend coverage
и production build; Chrome DevTools MCP проверяет настоящий WebGL отдельно.
Исторические GPU-измерения legacy — [PERFORMANCE](docs/PERFORMANCE.md).

100k/миллион — synthetic-нагрузки, не число реальных положений.
Открыты общий временной индекс, многосекторный менеджер и динамический LOD,
остальные реальные тела, вращение, поверхности и свободный полёт.
Legacy-текстуры используют CDN; offline-каталог не делает их автономными.
Сохраняются legacy-перекрытия крупных synthetic-мешей и предупреждение build
о JS chunk >500 kB. Пять физических центров эти ограничения не расширяют.
