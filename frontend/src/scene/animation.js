import * as THREE from 'three';
import { placeOnOrbit } from '../bodies/index.js';

/** Per-frame updates and the render call.
 *
 * Only `Object3D` transforms are touched here. Materials, geometries and
 * textures are shared across the whole catalog (see `bodies/resources.js`) and
 * must never be mutated or disposed from here.
 */
export function startAnimationLoop({ state, camera, controls, renderer, scene, solar, meshes, moons, localOrbits, blackHolesList, labels }) {
  let raf;

  // Переиспользуемые векторы: пока они создавались внутри цикла, на кадр
  // приходилось до нескольких тысяч аллокаций (на каждый спрайт-метку и на
  // каждое отслеживаемое тело) — постоянная нагрузка на сборщик мусора.
  const scratch = new THREE.Vector3();
  const followPos = new THREE.Vector3();
  const labelOffset = new THREE.Vector3();
  const followDelta = new THREE.Vector3();

  const animate = () => {
    raf = requestAnimationFrame(animate);

    // Deterministic illustrative orbits: date jumps and reverse time use the
    // same positions.
    const days = (state.simTime - Date.UTC(2000, 0, 1, 12)) / 86400000;

    solar.forEach((obj) => {
      const mesh = meshes.get(obj.id);
      if (!mesh || obj.kind === 'moon') return;
      const dist = mesh.userData.calculatedDistance;
      const periodDays = obj.period_days || (obj.au ? 365.25 * Math.pow(obj.au, 1.5) : 365);

      if (['planet', 'dwarf_planet', 'asteroid'].includes(obj.kind) && dist > 0) {
        mesh.userData.currentAngle = mesh.userData.initialAngle + (days / periodDays) * Math.PI * 2;
        mesh.position.x = Math.cos(mesh.userData.currentAngle) * dist;
        mesh.position.z = Math.sin(mesh.userData.currentAngle) * dist * 0.995;
      }
      mesh.rotation.y = days * 0.2;
    });

    moons.forEach(({ pivot, mesh, obj, parentId }) => {
      const parent = meshes.get(parentId);
      if (parent) pivot.position.copy(parent.position);
      const period = obj.period_days || 27.3;
      pivot.rotation.y = pivot.userData.initialAngle + (days / period) * Math.PI * 2;
      // Разные плоскости не дают лунам одной планеты слипнуться.
      pivot.rotation.x = pivot.userData.inclination || 0;
      mesh.rotation.y = days * 0.3;
    });

    // Экзопланеты: круговые орбиты вокруг хозяина. Орбитальные элементы
    // в каталоге отсутствуют, поэтому положение выводится из периода, а
    // радиус и наклон — визуальные (см. getLocalOrbitRadius).
    localOrbits.forEach(({ mesh, parentId, frame, radius, phase, period }) => {
      const parent = meshes.get(parentId);
      if (!parent) return;
      placeOnOrbit(mesh.position, parent.position, frame, radius, phase + (days / period) * Math.PI * 2);
      mesh.rotation.y = days * 0.4;
    });

    blackHolesList.forEach(({ disk, lensHalo, photonRing }) => {
      if (disk) disk.rotation.z = days * 0.45;
      if (lensHalo) lensHalo.rotation.z = -days * 0.25;
      if (photonRing) photonRing.quaternion.copy(camera.quaternion);
    });

    if (state.focusLight) {
      // Свет ставим в хозяина отслеживаемого тела: для экзопланет и лун
      // это даёт корректную terminator, а не равномерную заливку.
      const focus = state.followObject;
      const host = focus && focus.parent ? meshes.get(focus.parent) : null;
      if (host) {
        state.focusLight.position.copy(host.getWorldPosition(scratch));
        state.focusLight.intensity = 6;
      } else {
        state.focusLight.intensity = 0;
      }
    }

    labels.forEach(({ label, mesh, id }) => {
      mesh.getWorldPosition(scratch);
      labelOffset.set(0, (mesh.userData.displayRadius || 1) + 1.2, 0);
      label.position.copy(scratch).add(labelOffset);
      label.quaternion.copy(camera.quaternion);
      // Метки заводятся только для планет и карликовых, поэтому проверка
      // по типу здесь уже избыточна.
      label.visible = state.view === 'solar' && !(state.followObject && state.followObject.id === id);
    });

    if (state.followObject && meshes.has(state.followObject.id)) {
      const m = meshes.get(state.followObject.id);
      m.getWorldPosition(followPos);

      if (state.followCamera) {
        if (!state.lastFollowPos) {
          state.lastFollowPos = followPos.clone();
        }
        // Сдвигаем камеру ровно на столько, на сколько уехало тело, иначе
        // она догоняла бы объект с задержкой в один кадр.
        followDelta.copy(followPos).sub(state.lastFollowPos);
        camera.position.add(followDelta);
        controls.target.add(followDelta);
        state.lastFollowPos.copy(followPos);
      } else {
        state.lastFollowPos = null;
      }
    } else {
      state.lastFollowPos = null;
    }

    controls.update();
    renderer.render(scene, camera);
  };

  animate();

  return function stop() {
    cancelAnimationFrame(raf);
  };
}
