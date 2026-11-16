import * as THREE from 'three';
import { focalLength, screenRadius } from './lodManager.js';

/** Screen picking over the controller's current positions and visibility. */
export function createLODPicking({
  objects, positions, radii, levels, isGalaxyCluster, camera, domElement, group, galaxyGroup,
}) {
  const count = objects.length;
  const projected = new THREE.Vector3();
  return function pick(clientX, clientY) {
    const localVisible = group.visible;
    const galaxyVisible = galaxyGroup ? galaxyGroup.visible : false;
    if (!localVisible && !galaxyVisible) return null;

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
      // Never pick an object from a hidden scale or one that LOD has not
      // placed on screen yet (levels[i] === -1).
      const visible = isGalaxyCluster[i] ? galaxyVisible : localVisible;
      if (!visible || levels[i] < 0) continue;

      projected
        .set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
        .project(camera);
      if (projected.z < -1 || projected.z > 1) continue;

      const x = ((projected.x + 1) / 2) * rect.width;
      const y = ((1 - projected.y) / 2) * rect.height;
      const sdx = x - px;
      const sdy = y - py;
      const screenDistance = Math.sqrt(sdx * sdx + sdy * sdy);
      if (Number.isNaN(screenDistance)) continue;

      const dx = positions[i * 3] - camX;
      const dy = positions[i * 3 + 1] - camY;
      const dz = positions[i * 3 + 2] - camZ;
      const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
      const objectRadius = screenRadius(radii[i], distance, focal);
      const hitRadius = Math.min(Math.max(objectRadius, 7), 18);
      if (screenDistance > hitRadius) continue;

      if (!best || screenDistance < best.screenDistance
        || (screenDistance === best.screenDistance && distance < best.distance)) {
        best = { obj: objects[i], screenDistance, distance };
      }
    }

    return best ? best.obj : null;
  };
}
