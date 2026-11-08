# Производительность: измерения до/после (Фазы 1–2)

Все замеры сделаны на каталоге 100 000 синтетических объектов (`data/gen_catalog_100k.py`), viewport 1440×1000, headed Chrome (Apple M1 Pro, WebGL2 через ANGLE/Metal), стек на `http://localhost:5173`. FPS замеряется через rAF 3 секунды после прогрева; числа ниже — медиана трёх прогонов, если не указано иное.

## До оптимизаций (базовая линия)

| Метрика | Значение |
|---------|----------|
| Draw call (`renderer.info.render.calls`) | 245 |
| Треугольники | 35 476 706 |
| FPS (headed) | 11.8 |
| Heap (used JS heap) | ~245 МБ |
| LOD-уровни | [60 722 / 39 150 / 128] |
| `/api/objects` JSON (gzip) | 3.33 МБ |
| Бинар v2 | не было |

Источник: ROADMAP.md, секция Фаза 1; замер «до» до изменений LOD.

## После оптимизаций (исторический legacy-замер, 2026-11-02)

| Метрика | Значение | Изменение |
|---------|----------|-----------|
| Draw call | 44 | 245 → 44 (< 50 цель ✓) |
| Треугольники | 4 083 240 | 35.5 М → 4.1 М (×8.7 меньше) |
| FPS (headed, анимация) | **~39** (39.0 / 39.3 / 40.0) | 11.8 → ~39 (цель 30+ ✓) |
| FPS (headed, на паузе) | **~46** (42.9 / 46.7 / 46.8) | — |
| Heap (used JS heap) | ~252–268 МБ | ~245 МБ (без роста) |
| LOD-уровни | [43 547 / 56 433 / 20] | L2 бюджет 128 → 20 |
| Бинар v2 (100k, распакованный) | 13 000 172 Б | 130 байт/объект (< 20 МБ ✓) |
| Бинар v2 по сети (gzip, level 5) | 2 456 590 Б | 5.3× меньше, 18.9 % от raw |
| Полный JSON по сети (gzip) | 3 331 810 Б | v2+gzip в 1.36× меньше |
| v2 парсинг (binary-parse) | **~129 мс** (122–164) | было ~135–166 мс |
| Каталог загрузки (catalog-load) | **~180 мс** (172–368) | было ~280–347 мс |
| `/api/search` (warm, 100k) | **7–10 мс** на сервере, ~11.5 мс по HTTP | было ~124–129 мс |
| `/api/objects/{id}` | ~2 мс | было O(n) по каталогу |
| Повторная валидация (304) | ~2 мс, 0 байт | было 13 МБ |

Точное распределение LOD-уровней зависит от положения камеры; важен итог: сумма уровней равна числу объектов, L2 ограничен бюджетом 20.

## Причины улучшения и границы

- L1 сферы stars8×6 (96 треугольников), остальные 6×4 (48); L2 budget128→20.
- LOD читает локальные positions без getWorldPosition, скрывает placeholders,
  использует sqrt в горячих циклах; статичные объекты не переписывают GPU-буфер.
- На паузе орбиты/вращение не пересчитываются. Экзопланеты используют плоский
  базис/inline math; photon ring разворачивается к камере каждый кадр.
- scaleCatalog WeakMap по каталогу/режиму экономит повторное клонирование;
  производные строки общие, не мутировать. GPU-орбиты отложены: CPU LOD/пикинг
  требуют отдельной переделки.
- v2 batch TextDecoder/strings и gzip/ETag — [BINARY_CATALOG](BINARY_CATALOG.md).
  Slice удерживает строковый блок, gzip экономит сеть, не unpacked RAM/parse.
- Поисковые цифры выше относятся к историческому list-cache (построение 157 ms,
  ~93 Б/объект). Production теперь DiskCatalog/SQLite substring scan и content
  revision; старый size-mtime ETag/list index не описывают текущий runtime.

Метрики относятся к **legacy** на synthetic 100k, не физическому streaming.
Цель этапа 30 fps пройдена, продуктовая 60 fps открыта. Настоящий hardware GPU
и headless SwiftShader несопоставимы. Текущие backend/physical измерения:
[TEST_COVERAGE](TEST_COVERAGE.md).

## Как замерить самостоятельно

```bash
# 100k стек
python3 data/gen_catalog_100k.py
docker compose -f docker-compose.yml -f docker-compose.100k.yml up --build -d

# Открыть http://localhost:5173/?scene=legacy в headed Chrome (Apple M1 Pro / аппаратный GPU)
# В DevTools MCP: установить probe из tests/browser_smoke/common.py
#   (INSTALL_PROBE), переключиться в «Окрестности Солнца» и 3 секунды считать
#   кадры через requestAnimationFrame.
# Метрики: window.__astroverseSmoke().metrics (calls/triangles/points),
#   .lodCounts, .resources; heap — performance.memory.usedJSHeapSize.
# Для 100k: pytest tests/browser_smoke/ -m stack100k -v
#   (headless проверяет бюджеты draw call/треугольников, но не fps:
#    SwiftShader на 100k рисует ~0.5 кадра/с).

# Транспорт: размер по сети и распакованный размер
curl -s -o /dev/null -D- -H 'Accept-Encoding: gzip' \
  'http://localhost:5173/api/objects?format=v2'   # Content-Encoding: gzip, chunked
curl -s -o /dev/null -D- -H 'Accept-Encoding: identity' \
  'http://localhost:5173/api/objects?format=v2'   # Content-Length: 13000172
curl -s -o /dev/null -w '%{size_download}\n' -H 'Accept-Encoding: gzip' \
  'http://localhost:5173/api/objects?format=v2'   # 2456590

# Кэш: ETag и условный запрос
ET=$(curl -s -o /dev/null -D- 'http://localhost:5173/api/objects?format=v2' \
  | awk -F': ' 'tolower($1)=="etag"{print $2}' | tr -d '\r')
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' \
  -H "If-None-Match: $ET" 'http://localhost:5173/api/objects?format=v2'  # 304 0
```
