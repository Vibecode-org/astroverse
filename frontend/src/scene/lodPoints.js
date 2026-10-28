/** L0: один THREE.Points на все объекты каталога.
 *
 * Кастомный шейдер с gl_PointSize, зависящим от расстояния и свойств объекта.
 * Все объекты всегда находятся в геометрии; за видимость отвечает размер точки
 * (далёкие — видимые, ближние — нулевой размер, их рендерят на L1/L2).
 * Пикинг: raycast по Points с порогом в экранных координатах.
 */

import * as THREE from 'three';
import { objectColor, pointSize } from './lodManager.js';

// Вершинный шейдер: вычисляет gl_PointSize на основе расстояния до камеры
// и детерминированного размера объекта.
const LOD_POINTS_VERTEX_SHADER = `
attribute vec3 instanceColor;
attribute float instanceSize;
attribute float instanceAlpha;
attribute float instancePickId;
varying vec3 vColor;
varying float vAlpha;
varying float vPickId;

void main() {
  vColor = instanceColor;
  vAlpha = instanceAlpha;
  vPickId = instancePickId;

  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mvPosition;

  // Размер точки в пикселях: instanceSize уже в пикселях (задан на CPU).
  gl_PointSize = instanceSize;
}
`;

// Фрагментный шейдер: цветной круг с мягким краем и альфа-фади.
const LOD_POINTS_FRAGMENT_SHADER = `
varying vec3 vColor;
varying float vAlpha;
varying float vPickId;

void main() {
  // Мягкий круг: расстояние от центра в нормализованных координатах точки.
  float dist = length(gl_PointCoord - vec2(0.5));
  if (dist > 0.5) discard;

  // Мягкий край для анти-алиасинга.
  float edge = smoothstep(0.45, 0.5, dist);
  float alpha = (1.0 - edge) * vAlpha;

  gl_FragColor = vec4(vColor, alpha);
}
`;

export function createLODPoints(objects, camera) {
  const count = objects.length;

  // Typed arrays (SoA, K-2): все данные объекта в плоских массивах.
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const alphas = new Float32Array(count);
  const pickIds = new Float32Array(count);

  // Заполняем данные. Позиции обновляются каждый кадр в animation loop.
  objects.forEach((obj, i) => {
    const c = objectColor(obj);
    colors[i * 3] = c.r;
    colors[i * 3 + 1] = c.g;
    colors[i * 3 + 2] = c.b;
    sizes[i] = pointSize(obj, 2.0);
    alphas[i] = 1.0;
    pickIds[i] = i; // индекс в массиве объектов для пикинга
  });

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('instanceColor', new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute('instanceSize', new THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute('instanceAlpha', new THREE.BufferAttribute(alphas, 1));
  geometry.setAttribute('instancePickId', new THREE.BufferAttribute(pickIds, 1));

  const material = new THREE.ShaderMaterial({
    vertexShader: LOD_POINTS_VERTEX_SHADER,
    fragmentShader: LOD_POINTS_FRAGMENT_SHADER,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexColors: true,
  });

  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false; // все точки всегда в фрустуме для простоты пикинга
  points.userData = { lodLevel: 0, objectCount: count };

  // Переиспользуемый вектор для обновления позиций.
  const _scratchPos = new THREE.Vector3();

  return {
    points,
    geometry,
    material,
    // Обновить позиции всех точек из meshes (вызывается каждый кадр).
    updatePositions: (meshes) => {
      const posAttr = geometry.attributes.position;
      for (let i = 0; i < count; i++) {
        const mesh = meshes.get(objects[i].id);
        if (mesh) {
          mesh.getWorldPosition(_scratchPos);
          posAttr.setXYZ(i, _scratchPos.x, _scratchPos.y, _scratchPos.z);
        }
      }
      posAttr.needsUpdate = true;
    },
    // Установить размеры и альфа точек для LOD.
    // L0-объекты видны как точки; L1/L2-объекты имеют микро-размер (не ноль,
    // чтобы WebGL не отбрасывал примитив) и нулевую альфу.
    setPointSizes: (lodLevels, screenRadii, fadeAlphas) => {
      const sizeAttr = geometry.attributes.instanceSize;
      const alphaAttr = geometry.attributes.instanceAlpha;
      for (let i = 0; i < count; i++) {
        const level = lodLevels[i];
        if (level === 0) {
          // L0: точка видна. Размер зависит от базового размера объекта,
          // альфа — от коэффициента фади (плавное затухание при приближении к L1).
          sizeAttr.setX(i, sizes[i]);
          alphaAttr.setX(i, fadeAlphas[i]);
        } else {
          // L1/L2: точка невидима (микро-размер, нулевая альфа).
          sizeAttr.setX(i, 0.01);
          alphaAttr.setX(i, 0.0);
        }
      }
      sizeAttr.needsUpdate = true;
      alphaAttr.needsUpdate = true;
    },
  };
}

/** Пикинг на L0: raycast по Points с порогом в экранных координатах.
 *
 * Возвращает индекс объекта в массиве objects или null.
 */
export function pickLODPoints(points, raycaster, camera, objects, pointerX, pointerY, domElement) {
  const rect = domElement.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;

  const pointer = new THREE.Vector2(
    ((pointerX - rect.left) / rect.width) * 2 - 1,
    -((pointerY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(pointer, camera);
  raycaster.params.Points = { threshold: 3.0 };

  const hits = raycaster.intersectObject(points, false);
  if (hits.length === 0) return null;

  // Ближайший hit — выбранный объект.
  const hit = hits[0];
  const pickId = hit.index;
  if (pickId != null && pickId >= 0 && pickId < objects.length) {
    return pickId;
  }
  return null;
}
