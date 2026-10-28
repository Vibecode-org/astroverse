/** L1: InstancedMesh на вид (star, planet, exoplanet, и т.д.).
 *
 * Пер-инстансные матрица и цвет (RGBA, где A — коэффициент фади).
 * Объекты на средней дистанции рендерятся здесь вместо отдельных мешей.
 * При приближении объект переходит на L2 (индивидуальный меш), и его инстанс
 * скрывается (scale = 0).
 */

import * as THREE from 'three';
import { objectColor } from './lodManager.js';

const SHELL_SEGMENTS = 24;
const SHELL_RINGS = 16;

/** Геометрия оболочки, общая для всех инстансов одного вида. */
function shellGeometry(radius) {
  return new THREE.SphereGeometry(radius, SHELL_SEGMENTS, SHELL_RINGS);
}

/** Материал инстансов с поддержкой per-инстансного цвета (RGBA).
 * Не используется sharedMaterial, потому что нужен vertexColors + transparent
 * для альфа-фади на каждый инстанс.
 */
function shellMaterial(isStar) {
  if (isStar) {
    return new THREE.MeshBasicMaterial({
      color: 0xffffff,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
    });
  }
  return new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.8,
    metalness: 0.05,
    vertexColors: true,
    transparent: true,
    depthWrite: false,
  });
}

/** Создаёт InstancedMesh для одного вида объектов.
 *
 * @param {string} kind - вид объекта (star, planet, exoplanet, …)
 * @param {Array} objects - объекты этого вида (из глобального массива)
 * @param {Array} globalIndices - индексы этих объектов в глобальном массиве objects
 * @param {THREE.Camera} camera
 * @returns {Object} { mesh, kind, update(lodLevels, screenRadii, meshes, fadeAlphas) }
 */
export function createKindInstanced(kind, objects, globalIndices, camera) {
  if (objects.length === 0) return null;

  // Определяем представительный радиус (максимальный в виде).
  let maxRadius = 0.4;
  let isStar = false;
  for (const obj of objects) {
    const r = obj.displayRadius || obj.radius || 0.4;
    if (r > maxRadius) maxRadius = r;
    if (obj.kind === 'star') isStar = true;
  }

  const geometry = shellGeometry(maxRadius);
  const material = shellMaterial(isStar);

  const mesh = new THREE.InstancedMesh(geometry, material, objects.length);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
  mesh.frustumCulled = false;
  mesh.userData = { lodLevel: 1, kind, objectCount: objects.length };

  // Per-instance цвет RGBA через InstancedBufferAttribute (4 компонента на инстанс).
  // A-компонента используется для альфа-фади.
  const colors = new Float32Array(objects.length * 4);
  objects.forEach((obj, i) => {
    const c = objectColor(obj);
    colors[i * 4] = c.r;
    colors[i * 4 + 1] = c.g;
    colors[i * 4 + 2] = c.b;
    colors[i * 4 + 3] = 1.0; // alpha, обновляется каждый кадр
  });
  mesh.instanceColor = new THREE.InstancedBufferAttribute(colors, 4);

  // Матрицы инстансов (обновляются каждый кадр).
  const matrices = new Float32Array(objects.length * 16);

  // Инициализируем все матрицы единичными.
  for (let i = 0; i < objects.length; i++) {
    matrices[i * 16 + 15] = 1;
  }

  return {
    mesh,
    kind,
    objectCount: objects.length,
    globalIndices,
    matrices,
    /** Обновить матрицы и альфа инстансов на основе LOD уровней.
     *
     * lodLevels — Int8Array, индексированный по глобальному индексу объекта.
     * screenRadii — Float32Array, индексированный по глобальному индексу.
     * meshes — Map<id, THREE.Mesh> для получения worldMatrix.
     * fadeAlphas — Float32Array, коэффициент альфа-фади (0..1).
     */
    update(lodLevels, screenRadii, meshes, fadeAlphas) {
      const colorAttr = mesh.instanceColor;

      for (let i = 0; i < objects.length; i++) {
        const globalIdx = globalIndices[i];
        const level = lodLevels[globalIdx];
        const alpha = fadeAlphas[globalIdx];

        if (level === 1) {
          const obj = objects[i];
          const m = meshes.get(obj.id);
          if (m) {
            m.updateMatrixWorld();
            m.matrixWorld.toArray(matrices, i * 16);
          }
          // Устанавливаем цвет с альфой.
          colorAttr.setX(i * 4, colorAttr.array[i * 4]); // r (уже установлен)
          colorAttr.setY(i * 4, colorAttr.array[i * 4 + 1]); // g
          colorAttr.setZ(i * 4, colorAttr.array[i * 4 + 2]); // b
          colorAttr.setW(i * 4, alpha); // a — фади
        } else {
          // Не-L1 инстанс: нулевой масштаб, нулевая альфа.
          matrices[i * 16 + 0] = 0;
          matrices[i * 16 + 5] = 0;
          matrices[i * 16 + 10] = 0;
          matrices[i * 16 + 15] = 1;
          colorAttr.setW(i * 4, 0.0);
        }
      }

      mesh.count = objects.length; // всегда рендерим все инстансы, невидимые имеют scale=0 и alpha=0
      mesh.instanceMatrix.needsUpdate = true;
      colorAttr.needsUpdate = true;
    },
    /** Установить видимость всего InstancedMesh (вкл/выкл весь вид). */
    setVisible(visible) {
      mesh.visible = visible;
    },
  };
}

/** Группирует объекты по виду и создаёт InstancedMesh для каждого вида. */
export function createLODInstanced(objects, camera) {
  const byKind = new Map();
  const globalIndicesByKind = new Map();
  for (let i = 0; i < objects.length; i++) {
    const obj = objects[i];
    const k = obj.kind;
    if (!byKind.has(k)) {
      byKind.set(k, []);
      globalIndicesByKind.set(k, []);
    }
    byKind.get(k).push(obj);
    globalIndicesByKind.get(k).push(i);
  }

  const instancedByKind = new Map();
  for (const [kind, objs] of byKind) {
    const gIndices = globalIndicesByKind.get(kind);
    const inst = createKindInstanced(kind, objs, gIndices, camera);
    if (inst) instancedByKind.set(kind, inst);
  }

  return { instancedByKind };
}
