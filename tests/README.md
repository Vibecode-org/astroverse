# Тесты Astroverse

## Структура

```text
tests/
├── conftest.py                      # общие pytest-фикстуры
├── test_catalog.py                  # валидация, загрузка, запись каталога
├── test_api.py                      # FastAPI: /health, /objects, /live-ephemeris
├── test_build_catalog.py            # сборщик каталога (offline/online)
├── test_entrypoint.py               # точка входа бэкенда
└── browser_smoke/                   # Playwright smoke-тесты (pytest)
    ├── conftest.py                  # browser context, page, probe
    ├── smoke_load.py                # загрузка страницы, canvas, нет pageerror
    ├── smoke_views.py               # переключение видов, камера
    ├── smoke_time.py                # дата, пауза, скорость
    ├── smoke_picking.py             # выбор объекта, follow, клик по canvas
    └── smoke_search.py              # поиск и фильтрация
```

## Backend-тесты (unittest)

Выполняются внутри Docker-контейнера, без установки зависимостей на хост:

```bash
docker compose build backend
docker compose run --rm --no-deps -w /app backend \
  python -m unittest discover -s tests -t . -v
```

Флаг `-w /app` **обязателен**: `WORKDIR` образа — `/app/backend`, а тесты лежат в `/app/tests`. Без него падает `ModuleNotFoundError: data`.

Браузерные smoke-тесты (`browser_smoke/smoke_*.py`) — на pytest и выполняются **вне** `unittest discover`: они названы `smoke_*.py`, а не `test_*.py`, поэтому контейнер их не импортирует (в нём нет pytest/playwright).

## Browser smoke (pytest + Playwright)

Используют настоящий Chrome: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.
Адрес приложения фиксирован: `http://localhost:5173`.

Frontend и API должны быть запущены, каталог должен содержать **3471 объект**.

```bash
python3 -m venv /tmp/astroverse-smoke-env
/tmp/astroverse-smoke-env/bin/python -m pip install playwright
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -v
```

Один модуль или тест:

```bash
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/smoke_time.py -v
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/smoke_time.py::TestTime::test_date_jumps_pause_resume_and_speed -v
```

Для видимого окна:

```bash
SMOKE_HEADED=1 /tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -v
```

Окружение во временном каталоге: после очистки повторите установку. `playwright install` не нужен — используется установленный Chrome.

## Покрытие browser smoke

| Модуль | Что проверяет |
|---|---|
| `smoke_load` | Каталог 3471, видимый canvas, реальная сцена и продвижение render frame без `pageerror` |
| `smoke_views` | Пауза → окрестности → галактика → Солнечная система: видимость групп, позиции камеры, продолжающийся рендер и неподвижная дата |
| `smoke_time` | Три `+1 день` и три `-1 день`: разбор русской даты из `.scaleBadge`, движение Земли и возврат в исходную позицию; фиксация даты/позиции на паузе, движение после продолжения; `.speedChip`: ×1 → ×1.5 → ×2.25 → ×1.125 |
| `smoke_picking` | Земля из `.objectRow` по точному тексту `.objectName`: панель, target в мировой позиции Земли, follow off/on, реальное перемещение камеры вместе с Землёй после продолжения, закрытие панели; проекция мировой позиции на canvas, проверка frustum/видимости/отсутствия UI поверх точки, настоящий `page.mouse.click`; выбран именно каталоговый `planet`, не Three `Mesh` |
| `smoke_search` | Фильтрация списка по имени, latin-имени, описанию; очистка поиска |

Каждый тест получает новый browser context (`ru-RU`, UTC, 1440×1000), чтобы состояние тестов не зависело от порядка. Навигация/загрузка ограничены 45 секундами, остальные ожидания — 10 секундами на операцию. `pageerror` собираются с момента до навигации и проверяются при завершении каждого теста. Консольные предупреждения не считаются `pageerror`.

## Намеренная диагностическая интроспекция

Только `page.evaluate` устанавливает `window.__astroverseSmoke` в текущей тестовой странице. Функция каждый раз начинает с DOM `#root` → ключ `__reactContainer$…` → `.stateNode.current` (актуальный HostRoot), обходит fibers и цепочки hooks и ищет `memoizedState.current.scene` (включая вложенный `current` wrapper). Имена компонентов и порядок hooks не используются; поддержаны `useRef({})` и прежний `useState({current: {}})`.

Возвращается сериализуемый JSON: view, видимость system/nearby/galaxy, camera.position, controls.target, локальная и мировая позиции Земли, followCamera/followObject, renderer.info.render.frame и текст даты. Для клика дополнительно возвращается экранная проекция; Three берётся из уже существующих объектов, без импорта/подмены библиотеки.

Это **private React internals**, намеренно используемые для диагностики, а не публичный контракт. После обновления React структура fibers может потребовать обновления тестового probe. Никаких production hooks или изменений исходников приложения нет. Probe не задаёт дату, камеру или выбор: все пользовательские изменения выполняются через UI.
