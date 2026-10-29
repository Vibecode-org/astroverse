/** Deep-sky LOD controller.
 *
 * Only the `local` scale participates for now. The Solar System keeps its
 * detailed meshes unconditionally: it is small (515 objects) and it is the
 * part of the scene where labels, rings, atmospheres and moons must stay
 * pixel-accurate even from the default camera. Deep sky is where thousands of
 * tiny meshes actually cost draw calls, so L0/L1 live there.
 *
 * The controller owns visibility of the deep-sky L2 meshes. `viewState` still
 * owns the per-scale group visibility; both are needed: the group decides
 * *which scale*, LOD decides *which representation within that scale*.
 */

import * as THREE from 'three';
import { LOD_THRESHOLDS, focalLength, lodLevel, screenRadius } from './lodManager.js';
import { createLODPoints } from './lodPoints.js';
import { createLODInstanced } from './lodInstanced.js';

const LOD_SCALE = 'local';

export function createLOD({ objects, meshes, camera, domElement, group }) {
  const lodObjects = objects.filter((obj) => obj.scale === LOD_SCALE);
  const count = lodObjects.length;

  const radii = new Float32Array(count);
  const positions = new Float32Array(count * 3);
  const levels = new Int8Array(count).fill(-1);

  const points = createLODPoints(lodObjects);
  const instances = createLODInstanced(lodObjects);
  group.add(points.object);
  for (const mesh of instances.meshes) group.add(mesh);

  const scratch = new THREE.Vector3();
  const projected = new THREE.Vector3();

  // Seed positions once. Objects with a parent (exoplanets) move every frame
  // and are refreshed in `update`; stars stay where the catalog put them.
  lodObjects.forEach((obj, i) => {
    radii[i] = obj.displayRadius ?? obj.radius ?? 0.4;
    const mesh = meshes.get(obj.id);
    if (!mesh) return;
    mesh.getWorldPosition(scratch);
    positions[i * 3] = scratch.x;
    positions[i * 3 + 1] = scratch.y;
    positions[i * 3 + 2] = scratch.z;
    points.setPosition(i, scratch);
  });
  points.commit();

  function update() {
    // Hidden scales cost nothing per frame. The first visible frame recomputes
    // levels from the current camera, so returning to the view is correct.
    if (!group.visible) return;

    const height = domElement.clientHeight || window.innerHeight || 1;
    const focal = focalLength(camera, height);
    points.setViewport(focal);

    const camX = camera.position.x;
    const camY = camera.position.y;
    const camZ = camera.position.z;

    for (let i = 0; i < count; i++) {
      const obj = lodObjects[i];
      const mesh = meshes.get(obj.id);
      if (!mesh) continue;

      if (obj.parent) {
        mesh.getWorldPosition(scratch);
        positions[i * 3] = scratch.x;
        positions[i * 3 + 1] = scratch.y;
        positions[i * 3 + 2] = scratch.z;
        points.setPosition(i, scratch);
      } else {
        scratch.set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);
      }

      const distance = Math.hypot(
        scratch.x - camX,
        scratch.y - camY,
        scratch.z - camZ,
      );
      const sr = screenRadius(radii[i], distance, focal);
      const next = lodLevel(sr, levels[i]);

      if (next !== levels[i]) {
        levels[i] = next;
        mesh.visible = next === 2;
        if (next === 1) instances.show(i, scratch, radii[i]);
        else instances.hide(i);
      } else if (next === 1 && obj.parent) {
        // Keep a moving exoplanet's instance in sync while it is at L1.
        instances.show(i, scratch, radii[i]);
      }
    }

    points.commit();
    instances.commit();
  }

  /** Screen-space pick for objects currently drawn as L0/L1.
   *
   * A raycast against `Points` would need a world-space threshold, which is
   * wrong at both ends of the scale; projecting candidates and comparing in
   * pixels is simple and gives a constant clickable area.
   */
  function pick(clientX, clientY) {
    if (!group.visible) return null;

    const rect = domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;

    const focal = focalLength(camera, domElement.clientHeight || rect.height);
    const px = clientX - rect.left;
    const py = clientY - rect.top;
    const camX = camera.position.x;
    const camY = camera.position.y;
    const camZ = camera.position.z;

    let best = null;

    for (let i = 0; i < count; i++) {
      projected
        .set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
        .project(camera);
      if (projected.z < -1 || projected.z > 1) continue;

      const x = ((projected.x + 1) / 2) * rect.width;
      const y = ((1 - projected.y) / 2) * rect.height;
      const screenDistance = Math.hypot(x - px, y - py);
      if (Number.isNaN(screenDistance)) continue;

      const distance = Math.hypot(
        positions[i * 3] - camX,
        positions[i * 3 + 1] - camY,
        positions[i * 3 + 2] - camZ,
      );
      const objectRadius = screenRadius(radii[i], distance, focal);
      // Small dots get a generous target; large objects keep their own size so
      // a click on empty space next to a star does not select it.
      const hitRadius = Math.min(Math.max(objectRadius, 7), 18);
      if (screenDistance > hitRadius) continue;

      if (!best || screenDistance < best.screenDistance
        || (screenDistance === best.screenDistance && distance < best.distance)) {
        best = { obj: lodObjects[i], screenDistance, distance };
      }
    }

    return best ? best.obj : null;
  }

  function counts() {
    const result = [0, 0, 0];
    for (let i = 0; i < count; i++) {
      if (levels[i] >= 0) result[levels[i]]++;
    }
    return result;
  }

  function dispose() {
    group.remove(points.object);
    for (const mesh of instances.meshes) group.remove(mesh);
    points.dispose();
    instances.dispose();
  }

  // Establish the initial representation before the first frame is drawn.
  update();

  return {
    update,
    pick,
    counts,
    dispose,
    thresholds: LOD_THRESHOLDS,
    objectCount: count,
  };
}
