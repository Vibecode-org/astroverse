# Физический L0/L1 и CPU/GPU-бюджеты

`physical/sectorFrame.js` проверяет/собирает кадр; `sectorManager.js` владеет
HTTP/admission/отменой; `physicalLayer.js` — GPU slots/LOD/picking.
`positions/1` centers сохраняются; [единицы/иерархия](HIERARCHY.md).
Legacy `scene/lodController.js`, `lodPicking.js`, `lodDetailedMeshes.js` — отдельный путь.

L0 — диск5CSSpx, L1 — кольцо15CSSpx с учётом DPR; это графические маркеры,
не измеренные радиусы. L1 enter≤20render units(2e6km), exit≥28(2.8e6km),
selected приоритетен;≤32L1, остальные L0. Циклически≤128LOD checks/RAF:
при4096 до32кадров. Загруженные computed centers не скрываются радиусом LOD.

Один Points/material/geometry,≤1draw call. Capacity8…4096 степенями2,
XYZ/color/level Float32=28B/slot,≤114688B. ID удерживает слот; свободные
переиспользуются, holes отбрасываются shader. Рост disposes старую geometry,
сохраняет renderer/material/Points; textures нет. Log-depth chunks включены.
Picking≤4096проекций: screen distance, при равенстве≤1e−6CSSpx — view depth,
затем lexical ID. Drag>5CSSpx/cancel/secondary pointer не выбирают.

## CPU/GPU admission: ограниченный этап 3.4/3.8 (2026-11-10)

Обычный manager: resident+staging+in-flight≤4096records/4MiBserialized/
32MiBdecoded estimate;4workers,queue≤128,response≤256KiB/128centers.
Резерв до fetch заменяется actual cost; manifest object_count резервирует rows,
без него rows проверяются после ответа, bytes покрывают decode; merge512B/row.
Это модель памяти, не RSS/driverRAM. Production — пять центров; fixture32×64:
2048rows,32unknown остаются null.

Continuous Now удерживает предыдущий набор в том же контексте: нужны место
двух наборов и запас ответов. Известный oversubscription отклоняется до fetch/
изменения счётчиков; siblings отменяются, old scene очищается, ошибка terminal
до явного нового контекста. Explicit дата/область освобождает старый набор;
отменённые workers дренируются до нового admission. Partial/fallback нет.

Обычный apply синхронен/атомарен≤4096rows до render; ошибка/empty очищает слой.
LOD меняет level, не fetch/UTC. p95,max budgets:apply16/50ms,LOD1/8ms,
ready→возврат render250/1000ms. Последняя метрика включает RAF/React/software
renderer, не monitor/GPU fence. Время готовности WeakMap; production не копит
историю. Camera/roundoff/rebase — [NAVIGATION](NAVIGATION.md).

## Opt-in расширение synthetic S-100k

[S100K](S100K.md) задаёт увеличенные лимиты и budgets. Большие flat frames
готовятся отменяемыми порциями; hierarchy decoder остаётся≤4096.
Renderer staging содержит XYZ/slots/bitmap/AABB; до atomic sync commit
LOD/picking читают прежний целый displayed frame. Staging origin фиксирован,
rebase компенсируется renderShift; canonical Float64 неизменны.
Общий deadline manager/renderer2ms между RAF; hidden-tab timeout32ms,
scheduler.yield или timer fallback. Операция/GC может превысить deadline.
Массовый real streaming/временной индекс/L2/поверхности открыты.
Команды — [tests/README](../tests/README.md), измерения — [HISTORY](HISTORY.md).
