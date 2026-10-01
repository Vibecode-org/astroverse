import * as THREE from 'three';
import { createBodyMesh, getLocalOrbitRadius, orbitFrame, orbitPhase, placeOnOrbit } from '../bodies/index.js';
import { equatorialXYZ, galacticXYZ } from '../bodies/utils/coordinates.js';

/** Build the deep-sky layers: nearby stars with their exoplanets, and galaxy
 * markers.
 *
 * Both are appended to the shared `meshes` map so that picking, camera focus
 * and follow-mode work identically for every scale.
 */
export function buildDeepSky(scaledObjects, nearby, galaxyMarkers, meshes) {
  const localOrbits = [];
  const blackHolesList = [];

  // Локальная сцена строится в два прохода: сначала корни, потом тела с
  // родителем. Раньше всё ставилось в equatorialXYZ, но NASA отдаёт
  // системную астрометрию — ra/dec/distance у планеты и её хозяина совпадают,
  // и планета оказывалась геометрически внутри меша звезды.
  const localObjects = scaledObjects.filter((o) => o.scale === 'local');
  const localIds = new Set(localObjects.map((o) => o.id));

  localObjects.filter((o) => !localIds.has(o.parent)).forEach((obj) => {
    const mesh = createBodyMesh(obj);
    mesh.position.copy(equatorialXYZ(obj));
    nearby.add(mesh);
    meshes.set(obj.id, mesh);
  });

  localObjects.filter((o) => localIds.has(o.parent)).forEach((obj) => {
    const parent = meshes.get(obj.parent);
    if (!parent) return;
    const mesh = createBodyMesh(obj);
    const radius = getLocalOrbitRadius(obj, parent.userData?.radius || 0.35);
    // Плоскость — общая для системы, фаза — своя у каждого тела.
    const frame = orbitFrame(obj.parent);
    const phase = orbitPhase(obj.id);
    mesh.position.copy(placeOnOrbit(new THREE.Vector3(), parent.position, frame, radius, phase));
    nearby.add(mesh);
    meshes.set(obj.id, mesh);
    localOrbits.push({ mesh, parentId: obj.parent, frame, radius, phase, period: obj.period_days || 365.25 });
  });

  scaledObjects.filter((o) => o.scale === 'galaxy').forEach((obj) => {
    const mesh = createBodyMesh(obj);
    mesh.position.copy(galacticXYZ(obj));
    galaxyMarkers.add(mesh);
    meshes.set(obj.id, mesh);

    if (mesh.userData?.isBlackHole) {
      blackHolesList.push(mesh.userData);
    }
  });

  return { localOrbits, blackHolesList };
}
