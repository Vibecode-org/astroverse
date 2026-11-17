# Astroverse

Браузерный 3D-планетарий: React + Three.js, FastAPI, Docker. Цель — все известные
на дату обновления тела с проверяемыми источниками; неизвестная физика — null.

```bash
docker compose up --build -d    # http://localhost:5173
# или make up; make down останавливает, сохраняя рабочую БД
```

Нужны Docker Compose v2/WebGL2, для Makefile — Make. Порт/LAN —
[.env.example](.env.example), логи — `docker compose logs -f`. Для старой установки
до пересоздания контейнера выполните [миграцию SQLite](docs/STARTUP.md).

## Что работает

- `/`: пять центров Sun/Earth/Moon/Mercury/Venus, offline DE440s, ICRF/SSB/km/TDB,
  UTC [2000-01-01,2027-06-28), положения выбранной даты и UTC принятого кадра.
- 3471 справочная карточка, поиск, bounded sectors; карточка не подтверждает положение.
- 6DoF, линейный floating origin, L0/L1, picking/refocus. `/?scene=legacy` —
  прежняя иллюстративная сцена. Synthetic S-100k проверен отдельно; аппаратные
  60+fps, реальный S-100k, поверхности и массовый physical streaming открыты.
- Startup открывает SQLite из volume; чистая установка копирует pinned bootstrap.
  Build/startup не требуют seed JSON/скачивания научных данных.
  Patches переживают обновления; backup/restore и ограничения — [STARTUP](docs/STARTUP.md).

## Управление и разработка

ЛКМ/колесо/ПКМ — вращение/zoom/панорама; touch — swipe/pinch. Поиск/маркер открывают
карточку, «Наблюдать» возвращает к телу. Полёт: W/S,A/D,R/F — движение,
стрелки/мышь — поворот,Q/E — крен,+/− — скорость,пробел — стоп.
Скорость полёта независима от симуляции; выход сохраняет положение камеры.

```bash
make test                      # backend
make coverage                  # backend + пороги
make scene SCENE=s100k          # отдельная тестовая сцена :5174
make scene-down
# frontend/: npm ci; npm run test:coverage; npm run build; npm run dev
```

Compose приложения — в корне, тестовый — `tests/docker/compose.yml`.
Команды — `make`. Test images/volumes отделены от рабочих.
Vite проксирует API на127.0.0.1:8000; обычный nginx публикует только frontend.
Runtime SQLite проверяется offline; uncached images/packages требуют доступа
к зависимостям. Legacy CDN-текстуры ещё не автономны; chunk>500kB — известное предупреждение.

| Читать | Для чего |
|---|---|
|[ROADMAP](ROADMAP.md)|Статус и следующие этапы|
|[STARTUP](docs/STARTUP.md)|SQLite, backup/restore, миграция|
|[COORDINATES](docs/COORDINATES.md),[SOURCES](docs/SOURCES.md)|Физические контракты и источники|
|[SECTORS](docs/SECTORS.md),[BINARY_CATALOG](docs/BINARY_CATALOG.md)|Storage и API|
|[HIERARCHY](docs/HIERARCHY.md),[NAVIGATION](docs/NAVIGATION.md),[PHYSICAL_LOD](docs/PHYSICAL_LOD.md),[S100K](docs/S100K.md)|Координаты и сцена|
|[tests/README](tests/README.md),[TEST_COVERAGE](docs/TEST_COVERAGE.md)|Команды и результаты|
|[AGENTS](AGENTS.md),[HISTORY](docs/HISTORY.md)|Владельцы/правила и краткая история|
