import * as THREE from 'three';
import { createBodyMesh, getLocalOrbitRadius, orbitFrame, orbitPhase, placeOnOrbit } from '../bodies/index.js';
import { equatorialXYZ, galacticXYZ } from '../bodies/utils/coordinates.js';

/** Placement of a root object (no parent).
 *
 * Binary v2 already carries the render position computed by the backend with
 * the same formulas as `equatorialXYZ`/`galacticXYZ`. Using it avoids shipping
 * ra/dec/distance/galactic fields to the browser for every one of 100k objects
 * and keeps the JSON path working as a fallback.
 *
 * Exoplanets are deliberately excluded: they are placed on orbits around their
 * host by `placeOnOrbit`, not at the parent's catalog position.
 */
function rootPosition(obj, scale) {
  if (Array.isArray(obj._binaryPosition)) {
    return new THREE.Vector3(...obj._binaryPosition);
  }
  return scale === 'galaxy' ? galacticXYZ(obj) : equatorialXYZ(obj);
}

/** Build the deep-sky layers: nearby stars with their exoplanets, and galaxy
 * markers.
 *
 * Local objects (stars, exoplanets, clusters) get a lightweight placeholder
 * (THREE.Object3D) at startup — no detailed geometry. The detailed L2 mesh is
 * created lazily by the LOD controller when the object enters L2 or is
 * selected. Galaxy nebula/galaxy/black_hole keep their detailed meshes (they
 * are recognisable and few in number).
 *
 * Everything is appended to the shared `meshes` map so that picking, camera
 * focus and follow-mode work identically for every scale.
 */
export function buildDeepSky(scaledObjects, nearby, galaxyMarkers, meshes) {
  const localOrbits = [];
  const blackHolesList = [];

  const localObjects = scaledObjects.filter((o) => o.scale === 'local');
  const localIds = new Set(localObjects.map((o) => o.id));

  // ---- Pass 1: root objects (stars, and cluster roots at galaxy scale) ----
  // Stars: placeholder, detailed mesh created lazily by LOD.
  localObjects.filter((o) => !localIds.has(o.parent) && o.kind !== 'cluster').forEach((obj) => {
    const placeholder = new THREE.Object3D();
    placeholder.position.copy(rootPosition(obj, 'local'));
    placeholder.userData.radius = obj.radius;
    placeholder.userData.displayRadius = obj.displayRadius ?? obj.radius ?? 0.4;
    placeholder.userData.obj = obj;
    placeholder.userData.lodScale = 'local';
    placeholder.frustumCulled = false;
    nearby.add(placeholder);
    meshes.set(obj.id, placeholder);
  });

  // Galaxy-scale clusters: placeholder, detailed mesh created lazily.
  scaledObjects.filter((o) => o.scale === 'galaxy' && o.kind === 'cluster').forEach((obj) => {
    const placeholder = new THREE.Object3D();
    placeholder.position.copy(rootPosition(obj, 'galaxy'));
    placeholder.userData.displayRadius = obj.displayRadius ?? obj.radius ?? 0.4;
    placeholder.userData.obj = obj;
    placeholder.userData.lodScale = 'galaxy';
    placeholder.frustumCulled = false;
    galaxyMarkers.add(placeholder);
    meshes.set(obj.id, placeholder);
  });

  // ---- Pass 2: children with parents (exoplanets around stars) ----
  localObjects.filter((o) => localIds.has(o.parent) && o.kind !== 'cluster').forEach((obj) => {
    const parent = meshes.get(obj.parent);
    if (!parent) return;
    const placeholder = new THREE.Object3D();
    const radius = getLocalOrbitRadius(obj, parent.userData?.radius || 0.35);
    const frame = orbitFrame(obj.parent);
    const phase = orbitPhase(obj.id);
    placeholder.position.copy(placeOnOrbit(new THREE.Vector3(), parent.position, frame, radius, phase));
    placeholder.userData.displayRadius = obj.displayRadius ?? obj.radius ?? 0.4;
    placeholder.userData.obj = obj;
    placeholder.userData.lodScale = 'local';
    placeholder.userData.orbit = { frame, radius, phase, period: obj.period_days || 365.25 };
    placeholder.frustumCulled = false;
    nearby.add(placeholder);
    meshes.set(obj.id, placeholder);
    localOrbits.push({
      mesh: placeholder,
      parent,
      parentId: obj.parent,
      frame,
      radius,
      phase,
      period: obj.period_days || 365.25,
      // Flat orbit basis. The animation loop runs this for every exoplanet on
      // every frame (~39k on the 100k catalog); six plain numbers are cheaper
      // to read than `frame.x.x`/`frame.y.y` property chains.
      basis: [frame.x.x, frame.x.y, frame.x.z, frame.y.x, frame.y.y, frame.y.z],
    });
  });

  // ---- Galaxy-scale nebula / galaxy / black_hole: keep detailed meshes (L2 always) ----
  scaledObjects.filter((o) => o.scale === 'galaxy' && o.kind !== 'cluster').forEach((obj) => {
    const mesh = createBodyMesh(obj);
    mesh.position.copy(rootPosition(obj, 'galaxy'));
    galaxyMarkers.add(mesh);
    meshes.set(obj.id, mesh);

    if (mesh.userData?.isBlackHole) {
      blackHolesList.push(mesh.userData);
    }
  });

  return { localOrbits, blackHolesList };
}
