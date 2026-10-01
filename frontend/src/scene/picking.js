import * as THREE from 'three';
import { objectScale } from '../bodies/index.js';

/** Click-to-select by raycasting against the catalog meshes.
 *
 * Returns a `detach()` that removes every listener it added — the caller wires
 * that into the effect cleanup, alongside renderer teardown.
 */
export function attachPicking({ domElement, camera, meshes, catalogByMesh, onPick }) {
  const raycaster = new THREE.Raycaster();
  raycaster.params.Points = { threshold: 1.2 };
  const pointer = new THREE.Vector2();

  // Отсекаем клик от перетаскивания камеры: без этого orbit-проводка
  // заканчивается «выделением» объекта, мимо которого тянули.
  let isDragging = false;
  let startX = 0;
  let startY = 0;

  const onPointerDown = (e) => {
    startX = e.clientX;
    startY = e.clientY;
    isDragging = false;
  };

  const onPointerMove = (e) => {
    if (Math.hypot(e.clientX - startX, e.clientY - startY) > 5) {
      isDragging = true;
    }
  };

  const onPointerUp = (event) => {
    if (isDragging) return;

    const rect = domElement.getBoundingClientRect();
    // Клик за пределами canvas даёт rect.width = 0 и, без этой проверки,
    // деление на ноль -> Infinity/NaN в координатах луча.
    if (!rect.width || !rect.height) return;
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);

    // Прячем объекты невидимой группы: иначе клик по «окрестностям Солнца»
    // попадает в планету, лежащую в невидимой солнечной системе.
    const candidates = [];
    for (const m of meshes.values()) {
      let visible = m.visible;
      let parent = m.parent;
      while (parent) { visible = visible && parent.visible; parent = parent.parent; }
      if (visible) candidates.push(m);
    }

    const hit = raycaster.intersectObjects(candidates, true)[0];
    if (!hit) return;
    // Groups (nebula, galaxy, black hole) are hit on a child, so walk up
    // until the owning catalog object is found.
    let mesh = hit.object;
    while (mesh && !catalogByMesh.has(mesh)) mesh = mesh.parent;
    const obj = catalogByMesh.get(mesh);
    if (obj) onPick(obj, objectScale(obj));
  };

  domElement.addEventListener('pointerdown', onPointerDown);
  domElement.addEventListener('pointermove', onPointerMove);
  domElement.addEventListener('pointerup', onPointerUp);

  return function detach() {
    domElement.removeEventListener('pointerdown', onPointerDown);
    domElement.removeEventListener('pointermove', onPointerMove);
    domElement.removeEventListener('pointerup', onPointerUp);
  };
}
