# Тесты Astroverse

## Структура

```text
tests/
├── test_catalog.py                  # валидация, загрузка, запись каталога
├── test_api.py                      # FastAPI: /health, /objects, /search, ETag, /live-ephemeris
├── test_build_catalog.py            # сборщик каталога (offline/online)
├── test_entrypoint.py               # точка входа бэкенда
└── browser_smoke/                   # Playwright smoke-тесты (pytest)
    ├── conftest.py                  # browser context, page, авто-скип по маркерам
    ├── common.py                    # URL, probe, helpers (switch_view, wait_row, …)
    ├── smoke_load.py                # загрузка страницы, canvas, нет pageerror
    ├── smoke_views.py               # переключение видов, камера
    ├── smoke_time.py                # дата, пауза, скорость
    ├── smoke_picking.py             # выбор объекта, follow, клик по canvas
    ├── smoke_lod.py                 # LOD: draw call, уровни, пикинг точки
    ├── smoke_search.py              # поиск и фильтрация
    ├── smoke_binary.py              # бинарный каталог v2, gzip-транспорт, утечки ресурсов
    └── smoke_stress.py              # 100k нагрузка (маркер stack100k)
```

Всего 109 backend-тестов (`grep -c "def test_" tests/test_*.py`). Отдельного
`tests/conftest.py` нет — фикстуры браузерных тестов лежат только в
`tests/browser_smoke/conftest.py`.

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

Frontend и API должны быть запущены, каталог должен содержать **3471 объект**
(это проверяет `smoke_load` по счётчику в `.topmeta`).
Сейчас это **20 тестов** на каталоге 3471 плюс **4 stress-теста** на 100k;
все используют общий `common.py` (URL, probe, helpers).
Файл `pytest.ini` в корне задаёт `python_files = smoke_*.py`, поэтому каталог
`tests/browser_smoke/` собирается обычным `pytest`.

### Маркеры стеков

Модули помечены `pytestmark = pytest.mark.stack3471` или `stack100k`.
`conftest.py::pytest_collection_modifyitems` опрашивает `/api/health` и
пропускает модули, которые не подходят к поднятому стеку, с причиной вида
`needs the 3471-object stack (served catalog: 100000)`. Поэтому не нужно
помнить про переменные окружения или отдельный файл: один и тот же запуск
работает на обоих стеках.

```bash
# обычный стек: 20 тестов, 4 stress-модуля пропущены
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -q

# 100k стек: только stress-модуль
python3 data/gen_catalog_100k.py
docker compose -f docker-compose.yml -f docker-compose.100k.yml up --build -d
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -m stack100k -v
```

Вернуться на обычный стек: `docker compose up --build -d` (без override).

### Helpers в `common.py`

| Helper | Назначение |
|---|---|
| `DEFAULT_OBJECTS` / `STRESS_OBJECTS` | 3471 и 100 000 — ожидаемые размеры каталогов |
| `served_object_count()` | число объектов из `/api/health` (0, если стек недоступен) |
| `VIEW_LABELS` | подписи кнопок видов в одном месте |
| `switch_view(page, view)` | клик по кнопке вида + ожидание `s.view === view` |
| `wait_row(page, name)` | ждёт ровно одну строку списка с точным именем и стабильную раскладку |
| `wait_lod_settled(page)` | ждёт, пока LOD перестанет создавать/удалять L2 (не фиксированный sleep) |
| `wait_state` / `parse_badge_date` | ожидание предиката по probe и разбор русской даты |

```bash
python3 -m venv /tmp/astroverse-smoke-env
/tmp/astroverse-smoke-env/bin/python -m pip install playwright pytest
/tmp/astroverse-smoke-env/bin/python -m pytest tests/browser_smoke/ -v
```

В headless-режиме Chrome запускается с `--enable-unsafe-swiftshader` и
`--use-angle=swiftshader`: без этого на машинах без доступного GPU не создаётся
WebGL-контекст. Для видимого окна: `SMOKE_HEADED=1 ... pytest ...`.

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
| `smoke_time` | Три `+1 день` и три `-1 день`: разбор русской даты из `.scaleBadge`, ожидание точной ожидаемой даты **и** обновления позиции Земли (дата приходит из React, позиция — из следующего кадра), возврат в исходную позицию; фиксация даты/позиции на паузе, движение после продолжения; `.speedChip`: ×1 → ×1 мин/с → ×1 ч/с и обратно |
| `smoke_picking` | Земля из `.objectRow` по точному тексту `.objectName`: панель, target в мировой позиции Земли, follow off/on, реальное перемещение камеры вместе с Землёй после продолжения, закрытие панели; проекция мировой позиции на canvas, проверка frustum/видимости/отсутствия UI поверх точки, настоящий `page.mouse.click`; выбран именно каталоговый `planet`, не Three `Mesh` |
| `smoke_lod` | В «Окрестностях Солнца» все 2733 объекта распределены по L0/L1 и рисуются меньше чем за 100 draw call; Proxima Cen на L1 выбирается кликом по canvas, хотя её детальный меш скрыт |
| `smoke_search` | Фильтрация списка по имени, latin-имени, описанию; очистка поиска |
| `smoke_binary` | v2 бинарный каталог загружается без полного JSON; id/name переживают roundtrip; выбор бинарного объекта открывает карточку (догрузка `/api/objects/{id}`); поиск через `/api/search?q=`; ресурсы (геометрии/материалы/текстуры) не растут при переключении local ↔ solar ↔ galaxy (LOD дожидается устойчивых `lodCounts`, а не фиксированного sleep); транспорт: `Content-Encoding: gzip` + `Vary`, тело распаковывается в валидный `ASTV`-блоб, при `Accept-Encoding: identity` сжатия нет |
| `smoke_stress` | 100 000 объектов: v2 < 20 МБ, парсинг < 2 с, загрузка < 8 с; локальный вид < 50 draw call, треугольники < 6 М; виртуализация списка (≤40 строк); выбор объекта открывает карточку |

Маркер `stack3471` стоит на всех модулях, кроме `smoke_stress`; `stack100k` —
только на `smoke_stress`. На 100k headless Chrome рисует через SwiftShader со
скоростью ~0.5 кадра/с, поэтому stress-модуль поднимает таймаут действий до 60 с
и прокликивает строку через `element.click()`: Playwright'у для обычного клика
нужен ack от кадра, а кадр длится ~2.5 с.

Каждый тест получает новый browser context (`ru-RU`, UTC, 1440×1000), чтобы состояние тестов не зависело от порядка. Навигация/загрузка ограничены 45 секундами, остальные ожидания — 10 секундами на операцию (60 с в `smoke_stress`). `pageerror` собираются с момента до навигации и проверяются при завершении каждого теста. Консольные предупреждения не считаются `pageerror`.

## Намеренная диагностическая интроспекция

Только `page.evaluate` устанавливает `window.__astroverseSmoke` в текущей тестовой странице. Функция каждый раз начинает с DOM `#root` → ключ `__reactContainer$…` → `.stateNode.current` (актуальный HostRoot), обходит fibers и цепочки hooks и ищет `memoizedState.current.scene` (включая вложенный `current` wrapper). Имена компонентов и порядок hooks не используются; поддержаны `useRef({})` и прежний `useState({current: {}})`.

Возвращается сериализуемый JSON: view, видимость system/nearby/galaxy, camera.position, controls.target, локальная и мировая позиции Земли, followCamera/followObject, renderer.info.render.frame, текст даты, метрики кадра (`calls`, `triangles`, `points`, `lines`) и счётчики LOD-уровней. Для клика дополнительно возвращается экранная проекция; Three берётся из уже существующих объектов, без импорта/подмены библиотеки.

Это **private React internals**, намеренно используемые для диагностики, а не публичный контракт. После обновления React структура fibers может потребовать обновления тестового probe. Никаких production hooks или изменений исходников приложения нет. Probe не задаёт дату, камеру или выбор: все пользовательские изменения выполняются через UI.
