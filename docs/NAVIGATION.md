# Свободная камера

`frontend/src/physical/flight.js` — ввод/6DoF;
`PhysicalScene.jsx` — Float64 опора, rebase, область manager.
Renderer/controls сохраняются. Поверхности, посадка и галактический полёт открыты.

## Управление

- W/S, A/D, R/F — движение по локальным осям; стрелки — yaw/pitch, Q/E — roll;
  левый drag — yaw/pitch, клик≤5CSSpx — выбор. Диагональ нормализована.
- +/− меняют скорость×2: 1…1e9km/s, начальная100000; поворот1rad/s.
  Время камеры реальное, независимо от simulation pause/multiplier/reverse.
- Отпускание/Space/«Стоп» останавливают без инерции; повтор keydown не отменяет
  Stop. Blur/hidden/editable focus/pointercancel/смена режима очищают ввод.
  dt<0 или>250ms отбрасывается без догоняния.
- Выбор в полёте открывает карточку без перемещения. «Наблюдать» — явный refocus
  и следование поддержанному центру; неизвестный возвращает к прежней опоре.
  Выход сохраняет позу/крен, orbit target впереди; «Наблюдать» сбрасывает крен.

После выхода idle OrbitControls.update ждёт настоящего change/autoRotate,
сохраняя точные позы у полюсов; drag/wheel возвращают damping.

## Время, координаты и загрузка

Опора полёта: замороженные canonical Float64, sector/system/body путь, offset km;
мировая камера не зависит от GPU Float32. Единица100000km. При local length>100
render units offset переносится в опору с противоположной трансляцией camera/
target/layer до render; quaternion/centers неизменны. Новое время двигает только
тела; null/error очищает слой. Вычитание компонентов путей до сложения сохраняет
заданную локальную детализацию при общем начале1e18km.

Охват при входе `max(3e6km,2×distance(camera,orbit target))`; сохраняется при
rebase/выходе, может расти при orbit zoom-out; refocus начинает новый.
Перевыбор при сдвиге>radius/8. Nearby `ox/oy/oz` — полный неподвижный ICRF/SSB
origin km, `dx/dy/dz` — смещение; без origin anchor движется.
Неполный/нечисловой origin отвергается до ETag; HTTP координаты±1e13km абсолютные.
После остановки грузится последняя область без экстраполяции/старой даты.
Staging фиксирует origin; commit компенсирует rebase общей линейной трансляцией
GPU/picking. До commit виден целый прежний frame; explicit refocus скрывает его.

## Допуски и бюджеты до итоговых измерений

Paused canonical centers побитово неизменны. CPU continuity≤1e−6km;
GPU roundoff≤max(1e−6render units, |value|×1e−7); rebase≤0.05CSSpx.
Допуски арифметические, не physical uncertainty; Horizons regression —1km.
Camera/apply/LOD p95, max≤1/8, 16/50, 1/8ms. Camera исключает перепроекцию;
apply включает decode/slots/transforms/rebase. CPU submission не GPU fence/fps;
resource cycles не исключают все JS/driver утечки.
Команды — [tests/README](../tests/README.md), результаты — [HISTORY](HISTORY.md).
