/** LOD-контроллер: управляет трёхуровневым рендером (L0 Points, L1 InstancedMesh, L2 меши).
 *
 * Инициализируется один раз при построении сцены. Каждый кадр:
 * 1. Вычисляет уровень LOD для каждого объекта (с гистерезисом)
 * 2. Обновляет видимость/размер точек (L0), инстансов (L1) и отдельных мешей (L2)
 * 3. Применяет альфа-фади для плавных переходов между уровнями
 *
 * Состояние уровней хранится в замыкании (K-6: нет глобальных синглтонов).
 */

import * as THREE from 'three';
import { createLODPoints, pickLODPoints } from './lodPoints.js';
import { createLODInstanced } from './lodInstanced.js';
import { lodLevel as calcLodLevel, fadeAlpha as calcFadeAlpha, LOD_THRESHOLDS } from './lodManager.js';

/** Инициализирует LOD-систему после построения всех мешей.
 *
 * @param {Object} params
 * @param {THREE.Scene} params.scene
 * @param {THREE.Camera} params.camera
 * @param {Array} params.objects - scaled catalog objects
 * @param {Map} params.meshes - existing per-object meshes (L2), Map<id, Mesh>
 * @param {HTMLElement} params.domElement - canvas для пикинга
 * @returns {Object} LOD API: { points, instancedByKind, update, pick, dispose }
 */
export function initLOD({ scene, camera, objects, meshes, domElement }) {
  const count = objects.length;

  // Состояние уровней для каждого объекта (индекс в массиве objects -> уровень 0/1/2).
  const lodLevels = new Int8Array(count);
  lodLevels.fill(0);

  // Экранные радиусы (пересчитываются каждый кадр).
  const screenRadii = new Float32Array(count);

  // Коэффициенты альфа-фади для плавных переходов (0..1).
  const fadeAlphas = new Float32Array(count);
  fadeAlphas.fill(1.0);

  // --- L0: Points на все объекты ---
  const { points, geometry, material: pointsMaterial, updatePositions, setPointSizes } =
    createLODPoints(objects, camera);
  scene.add(points);

  // --- L1: InstancedMesh по видам ---
  const { instancedByKind } = createLODInstanced(objects, camera);
  for (const inst of instancedByKind.values()) {
    scene.add(inst.mesh);
  }

  // Вспомогательные векторы.
  const camPos = new THREE.Vector3();
  const worldPos = new THREE.Vector3();

  /** Вычисляет уровни LOD и коэффициенты фади для всех объектов. */
  function computeLevels() {
    camPos.copy(camera.position);
    const height = domElement?.clientHeight || window.innerHeight;
    const fov = (camera.fov * Math.PI) / 180;
    const focalLength = height / 2 / Math.tan(fov / 2);

    for (let i = 0; i < count; i++) {
      const obj = objects[i];
      const mesh = meshes.get(obj.id);
      if (!mesh) continue;

      mesh.getWorldPosition(worldPos);
      const distance = camPos.distanceTo(worldPos) || 0.001;
      const displayRadius = obj.displayRadius || obj.radius || 0.4;

      // Угловой радиус в пикселях.
      const sr = (displayRadius / distance) * focalLength;
      screenRadii[i] = sr;

      // Уровень с гистерезисом.
      const prev = lodLevels[i];
      const next = calcLodLevel(sr, prev);
      lodLevels[i] = next;

      // Коэффициент фади для плавного перехода между уровнями.
      // L0 -> L1: точка затухает по мере приближения к порогу L1_ENTER.
      // L1 -> L2: инстанс затухает по мере приближения к порогу L2_ENTER.
      // L2 -> L1: меш затухает при удалении от порога L2_EXIT.
      if (next === 0) {
        // L0: точка видна, фади при приближении к L1_ENTER.
        fadeAlphas[i] = calcFadeAlpha(sr, 0, LOD_THRESHOLDS.L1_EXIT, LOD_THRESHOLDS.L1_ENTER);
      } else if (next === 1) {
        // L1: инстанс виден. Фади на границах L1_ENTER и L2_ENTER.
        if (prev === 0) {
          // Только что перешли из L0 в L1: фади от 0 к 1.
          fadeAlphas[i] = calcFadeAlpha(sr, 1, LOD_THRESHOLDS.L1_EXIT, LOD_THRESHOLDS.L1_ENTER);
        } else if (prev === 2) {
          // Только что перешли из L2 в L1: фади от 1 к 0 при удалении.
          fadeAlphas[i] = calcFadeAlpha(sr, 1, LOD_THRESHOLDS.L2_EXIT, LOD_THRESHOLDS.L2_ENTER);
        } else {
          fadeAlphas[i] = 1.0;
        }
      } else {
        // L2: меш виден, фади при приближении к L2_ENTER.
        fadeAlphas[i] = calcFadeAlpha(sr, 2, LOD_THRESHOLDS.L2_EXIT, LOD_THRESHOLDS.L2_ENTER);
      }
    }
  }

  /** Обновляет видимость всех трёх уровней. Вызывается каждый кадр. */
  function update() {
    computeLevels();

    // L0: обновляем позиции точек (объекты движутся по орбитам).
    updatePositions(meshes);

    // L0: размер и альфа точек (видимые только для уровня 0).
    setPointSizes(lodLevels, screenRadii, fadeAlphas);

    // L1: видимость и альфа инстансов.
    for (const inst of instancedByKind.values()) {
      inst.update(lodLevels, screenRadii, meshes, fadeAlphas);
    }

    // L2: видимость и альфа отдельных мешей.
    for (let i = 0; i < count; i++) {
      const obj = objects[i];
      const mesh = meshes.get(obj.id);
      if (!mesh) continue;
      const level = lodLevels[i];
      mesh.visible = level === 2;
      // Альфа-фади для плавного появления при переходе на L2.
      if (mesh.material) {
        // Клонируем материал только если нужно установить уникальную альфу,
        // чтобы не мутировать shared ресурс (resources.js).
        if (fadeAlphas[i] < 1.0 && level === 2) {
          if (!mesh.material.userData._lodAlphaClone) {
            const cloned = mesh.material.clone();
            cloned.userData._lodAlphaClone = true;
            mesh.material = cloned;
          }
          mesh.material.opacity = fadeAlphas[i];
          mesh.material.transparent = true;
        } else if (fadeAlphas[i] >= 1.0 && mesh.material.userData._lodAlphaClone) {
          // Возвращаем общий материал, когда фади не нужен.
          mesh.material.userData._lodAlphaClone = false;
          // Не можем легко вернуть общий материал без ссылки на него,
          // но opacity=1.0 и transparent=false достаточно для визуального эффекта.
          mesh.material.opacity = 1.0;
          mesh.material.transparent = false;
        }
      }
    }
  }

  /** Пикинг: пробует все три уровня, возвращает id первого hit. */
  function pick(raycaster, pointerX, pointerY) {
    // L2: отдельные меши (самые точные).
    const l2Hit = pickL2(raycaster, pointerX, pointerY, domElement, camera, meshes);
    if (l2Hit !== null) return l2Hit;

    // L1: InstancedMesh.
    const l1Hit = pickL1(raycaster, pointerX, pointerY, domElement, camera, instancedByKind, objects);
    if (l1Hit !== null) return l1Hit;

    // L0: Points.
    const l0Hit = pickLODPoints(points, raycaster, camera, objects, pointerX, pointerY, domElement);
    if (l0Hit !== null) return l0Hit;

    return null;
  }

  /** Освобождает ресурсы. */
  function dispose() {
    scene.remove(points);
    geometry.dispose();
    pointsMaterial.dispose();
    for (const inst of instancedByKind.values()) {
      scene.remove(inst.mesh);
      // Не.dispose() геометрию и материал — они shared (resources.js).
    }
  }

  return {
    points,
    instancedByKind,
    lodLevels,
    screenRadii,
    fadeAlphas,
    update,
    pick,
    dispose,
  };
}

/** Пикинг L2: raycast по видимым отдельным мешам. */
function pickL2(raycaster, pointerX, pointerY, domElement, camera, meshes) {
  const rect = domElement.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;

  const pointer = new THREE.Vector2(
    ((pointerX - rect.left) / rect.width) * 2 - 1,
    -((pointerY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(pointer, camera);

  const candidates = [];
  for (const mesh of meshes.values()) {
    if (!mesh.visible) continue;
    let vis = true;
    let parent = mesh.parent;
    while (parent) { vis = vis && parent.visible; parent = parent.parent; }
    if (vis) candidates.push(mesh);
  }

  const hit = raycaster.intersectObjects(candidates, true)[0];
  if (!hit) return null;

  // Ищем корневой меш в meshes Map, поднимаясь по иерархии.
  let node = hit.object;
  while (node && node.parent) {
    if (meshes.has(node.userData?.id || node.name || '')) {
      return node.userData?.id || node.name || '';
    }
    node = node.parent;
  }
  // Также проверяем сам hit.object.
  if (meshes.has(hit.object.userData?.id || hit.object.name || '')) {
    return hit.object.userData?.id || hit.object.name || '';
  }

  // Fallback: ищем по ссылке на меш.
  for (const [id, m] of meshes) {
    if (m === hit.object || m === hit.object.parent) return id;
  }
  return null;
}

/** Пикинг L1: raycast по InstancedMesh. */
function pickL1(raycaster, pointerX, pointerY, domElement, camera, instancedByKind, objects) {
  const rect = domElement.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;

  const pointer = new THREE.Vector2(
    ((pointerX - rect.left) / rect.width) * 2 - 1,
    -((pointerY - rect.top) / rect.height) * 2 + 1,
  );

  // Предвычисляем mapping kind -> объекты для быстрого доступа.
  const byKind = new Map();
  for (const obj of objects) {
    if (!byKind.has(obj.kind)) byKind.set(obj.kind, []);
    byKind.get(obj.kind).push(obj);
  }

  for (const inst of instancedByKind.values()) {
    if (!inst.mesh.visible || inst.mesh.count === 0) continue;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObject(inst.mesh, false);
    if (hits.length === 0) continue;

    const hit = hits[0];
    const instanceId = hit.index;
    if (instanceId != null && instanceId >= 0) {
      const kindObjs = byKind.get(inst.kind);
      if (kindObjs && instanceId < kindObjs.length) {
        return kindObjs[instanceId].id;
      }
    }
  }
  return null;
}
