/** Deep-sky LOD controller.
 *
 * The `local` scale (stars, exoplanets) and galaxy-scale `cluster` objects
 * participate in LOD. The Solar System keeps its detailed meshes
 * unconditionally. Galaxy nebula/galaxy/black_hole keep their detailed meshes
 * (they are recognisable and few in number).
 *
 * The controller owns visibility of the deep-sky L2 meshes. `viewState` still
 * owns the per-scale group visibility; both are needed: the group decides
 * *which scale*, LOD decides *which representation within that scale*.
 *
 * L2 meshes are created lazily: at startup only lightweight placeholders
 * (THREE.Object3D without geometry) exist in the `meshes` map. When an object
 * enters L2 (close to camera or selected), a detailed mesh is built via
 * `createBodyMesh`, attached to the placeholder, and shown. When the object
 * leaves L2, the detailed mesh is disposed (shared resources from
 * `bodies/resources.js` are never touched) and removed.
 */

import * as THREE from 'three';
import { LOD_THRESHOLDS, focalLength, lodLevel, screenRadius } from './lodManager.js';
import { createLODPoints } from './lodPoints.js';
import { createLODInstanced } from './lodInstanced.js';
import { createL2Meshes } from './lodDetailedMeshes.js';

const LOD_SCALE_LOCAL = 'local';

// Frames over which an L2 mesh fades in/out at the L1↔L2 boundary.
const FADE_FRAMES = 24;

// Hard cap on simultaneously detailed L2 meshes. A dense catalog (the 100k
// synthetic stress catalog) can put thousands of objects above L2_ENTER at
// once; without a budget they become thousands of draw calls and the frame
// rate collapses. A detailed star also adds a corona sprite, so each L2 mesh
// costs ~2 draw calls: 20 keeps the local view under the <50 draw-call budget
// at 100k while still covering everything a user can meaningfully inspect.
const L2_BUDGET = 20;

/** Insert `index` into a descending top-K list, dropping the smallest entry.
 *  `indices`/`values` are reused between frames to avoid per-frame garbage. */
function insertTop(indices, values, index, value, limit) {
  if (indices.length >= limit && value <= values[values.length - 1]) return;
  let pos = indices.length;
  while (pos > 0 && values[pos - 1] < value) pos -= 1;
  indices.splice(pos, 0, index);
  values.splice(pos, 0, value);
  if (indices.length > limit) {
    indices.pop();
    values.pop();
  }
}

export function createLOD({ objects, meshes, camera, domElement, group, galaxyGroup }) {
  // Split objects into local and galaxy-cluster sets; each set gets its own
  // L0 Points / L1 InstancedMesh in the appropriate group.
  const localObjs = [];
  const galaxyClusterObjs = [];
  objects.forEach((obj) => {
    if (obj.scale === LOD_SCALE_LOCAL) localObjs.push(obj);
    else if (obj.scale === 'galaxy' && obj.kind === 'cluster') galaxyClusterObjs.push(obj);
  });

  const allObjs = [...localObjs, ...galaxyClusterObjs];
  const count = allObjs.length;

  const radii = new Float32Array(count);
  const positions = new Float32Array(count * 3);
  const levels = new Int8Array(count).fill(-1);
  const isGalaxyCluster = new Array(count).fill(false);

  // obj.id → index in allObjs
  const indexById = new Map();
  allObjs.forEach((obj, i) => {
    indexById.set(obj.id, i);
    if (obj.scale === 'galaxy' && obj.kind === 'cluster') isGalaxyCluster[i] = true;
  });

  // Placeholders are direct children of `group`/`galaxyGroup` and never move
  // between parents, so resolve the map once instead of 2× per object per
  // frame. On 100k objects that is 200k Map lookups per frame.
  const placeholders = new Array(count);

  const {
    states: l2State, create: createL2Mesh, destroy: destroyL2Mesh,
    ensure: ensureL2, release: releaseL2, applyFade,
  } = createL2Meshes({ meshes, indexById });

  // Separate L0/L1 representations for each set.
  const localPoints = createLODPoints(localObjs);
  const localInstances = createLODInstanced(localObjs);
  const galaxyClusterPoints = createLODPoints(galaxyClusterObjs);
  const galaxyClusterInstances = createLODInstanced(galaxyClusterObjs);

  group.add(localPoints.object);
  for (const mesh of localInstances.meshes) group.add(mesh);

  if (galaxyGroup && galaxyClusterObjs.length > 0) {
    galaxyGroup.add(galaxyClusterPoints.object);
    for (const mesh of galaxyClusterInstances.meshes) galaxyGroup.add(mesh);
  }

  // Map from allObjs index → { points, instances, localIndex } for L0/L1 ops.
  // `allObjs` is the concatenation of the two sets, so galaxy clusters start
  // after the local block.
  const repByIndex = new Array(count);
  localObjs.forEach((_, i) => {
    repByIndex[i] = { points: localPoints, instances: localInstances, localIndex: i };
  });
  galaxyClusterObjs.forEach((_, i) => {
    repByIndex[localObjs.length + i] = {
      points: galaxyClusterPoints,
      instances: galaxyClusterInstances,
      localIndex: i,
    };
  });

  const scratch = new THREE.Vector3();
  const projected = new THREE.Vector3();
  // Per-frame L2 budget state. `screenR` caches the projected radius from the
  // first pass so the second pass does not recompute it.
  const screenR = new Float32Array(count);
  const l2Allowed = new Uint8Array(count);
  const allowedList = [];
  const keepIdx = [];
  const keepSr = [];
  const newIdx = [];
  const newSr = [];

  // Group visibility is owned by `viewState`; the controller only needs to
  // react when it flips. Re-evaluating LOD for a hidden group every frame is
  // what used to create and destroy L2 meshes ~60 times per second.
  let lastLocalVisible = null;
  let lastGalaxyVisible = null;

  // Both groups are static (created at the origin, never transformed), so a
  // placeholder's world position is its local position. Keep the matrix path
  // as a fallback in case that ever changes.
  const identityMatrix = new THREE.Matrix4();
  const localMatrix = group.matrixWorld;
  const galaxyMatrix = galaxyGroup ? galaxyGroup.matrixWorld : null;
  const localIsIdentity = localMatrix.equals(identityMatrix);
  const galaxyIsIdentity = galaxyMatrix ? galaxyMatrix.equals(identityMatrix) : true;
  const readWorldPosition = (index, placeholder) => {
    scratch.copy(placeholder.position);
    if (isGalaxyCluster[index]) {
      if (!galaxyIsIdentity) scratch.applyMatrix4(galaxyMatrix);
    } else if (!localIsIdentity) {
      scratch.applyMatrix4(localMatrix);
    }
    return scratch;
  };

  // Seed positions once. Objects with a parent (exoplanets) move every frame
  // and are refreshed in `update`; stars stay where the catalog put them.
  allObjs.forEach((obj, i) => {
    radii[i] = obj.displayRadius ?? obj.radius ?? 0.4;
    const placeholder = meshes.get(obj.id);
    placeholders[i] = placeholder || null;
    if (!placeholder) return;
    // L0/L1 are drawn by the Points/InstancedMesh layers; the placeholder only
    // needs to be visible while it hosts an L2 mesh. Hiding it keeps the
    // renderer from traversing tens of thousands of empty Object3Ds every
    // frame (on 100k objects that was ~35% of the main thread).
    placeholder.visible = false;
    readWorldPosition(i, placeholder);
    positions[i * 3] = scratch.x;
    positions[i * 3 + 1] = scratch.y;
    positions[i * 3 + 2] = scratch.z;
    const rep = repByIndex[i];
    // `setPosition` expects an index into the per-scale Points cloud, not the
    // global `allObjs` index.
    if (rep) rep.points.setPosition(rep.localIndex, scratch);
  });
  localPoints.commit();
  if (galaxyClusterObjs.length > 0) galaxyClusterPoints.commit();

  /** Forget LOD state for one scale after its group visibility changed. */
  function resetGroup(isCluster) {
    for (let i = 0; i < count; i++) {
      if (isGalaxyCluster[i] !== isCluster) continue;
      destroyL2Mesh(i);
      levels[i] = -1;
      const rep = repByIndex[i];
      // A stale L1 matrix from before the switch must not reappear.
      if (rep) rep.instances.hide(rep.localIndex);
    }
  }

  function update() {
    const localVisible = group.visible;
    const galaxyVisible = galaxyGroup ? galaxyGroup.visible : false;

    // React to a scale switch exactly once. While a group is hidden its
    // objects are skipped entirely: no L2 creation, no per-frame churn.
    if (localVisible !== lastLocalVisible) {
      resetGroup(false);
      lastLocalVisible = localVisible;
    }
    if (galaxyVisible !== lastGalaxyVisible) {
      resetGroup(true);
      lastGalaxyVisible = galaxyVisible;
    }

    if (!localVisible && !galaxyVisible) return;

    const height = domElement.clientHeight || window.innerHeight || 1;
    const focal = focalLength(camera, height);

    // Point size and picking must agree on the same focal length.
    localPoints.setViewport(focal);
    if (galaxyClusterObjs.length > 0) galaxyClusterPoints.setViewport(focal);

    const camX = camera.position.x;
    const camY = camera.position.y;
    const camZ = camera.position.z;

    // ---- Pass 1: positions, projected radii and the L2 budget ----
    for (const i of allowedList) l2Allowed[i] = 0;
    allowedList.length = 0;
    keepIdx.length = 0;
    keepSr.length = 0;
    newIdx.length = 0;
    newSr.length = 0;

    // The pinned object (current selection) always keeps its detailed mesh.
    for (const [i, state] of l2State) {
      if (!state.pinned) continue;
      l2Allowed[i] = 1;
      allowedList.push(i);
    }

    for (let i = 0; i < count; i++) {
      const visible = isGalaxyCluster[i] ? galaxyVisible : localVisible;
      if (!visible) continue;

      const obj = allObjs[i];
      const placeholder = placeholders[i];
      if (!placeholder) continue;

      const rep = repByIndex[i];
      // Only objects on an orbit move after startup; a static star's L0
      // position was seeded once in the constructor. Re-uploading the whole
      // point cloud because nothing changed is pure bandwidth: at 100k that is
      // ~720 KB of positions per frame.
      if (obj.parent) {
        readWorldPosition(i, placeholder);
        positions[i * 3] = scratch.x;
        positions[i * 3 + 1] = scratch.y;
        positions[i * 3 + 2] = scratch.z;
        if (rep) rep.points.setPosition(rep.localIndex, scratch);
      } else {
        scratch.set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);
      }

      const dx = scratch.x - camX;
      const dy = scratch.y - camY;
      const dz = scratch.z - camZ;
      // `Math.hypot` is overflow-safe and ~5x slower than a plain sqrt; this
      // loop runs once per object per frame.
      const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
      const sr = screenRadius(radii[i], distance, focal);
      screenR[i] = sr;

      if (l2Allowed[i]) continue;
      // Existing meshes keep a hysteresis bonus (L2_EXIT); new ones must clear
      // the higher entry threshold. Only the largest few win the budget.
      if (l2State.has(i)) {
        if (sr >= LOD_THRESHOLDS.L2_EXIT) insertTop(keepIdx, keepSr, i, sr, L2_BUDGET);
      } else if (sr >= LOD_THRESHOLDS.L2_ENTER) {
        insertTop(newIdx, newSr, i, sr, L2_BUDGET);
      }
    }

    // Existing meshes first, then the remaining budget goes to the largest new
    // candidates. Without this cap a dense catalog creates thousands of L2
    // meshes at once (100k synthetic objects: 4 324 meshes → 7 120 draw calls).
    for (const i of keepIdx) {
      if (allowedList.length >= L2_BUDGET) break;
      if (l2Allowed[i]) continue;
      l2Allowed[i] = 1;
      allowedList.push(i);
    }
    for (let k = 0; k < newIdx.length && allowedList.length < L2_BUDGET; k++) {
      const i = newIdx[k];
      if (l2Allowed[i]) continue;
      l2Allowed[i] = 1;
      allowedList.push(i);
    }

    // ---- Pass 2: levels, instance visibility and L2 crossfade ----
    for (let i = 0; i < count; i++) {
      const visible = isGalaxyCluster[i] ? galaxyVisible : localVisible;
      if (!visible) continue;

      const obj = allObjs[i];
      const rep = repByIndex[i];
      if (!placeholders[i]) continue;

      scratch.set(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2]);

      const sr = screenR[i];
      let next = lodLevel(sr, levels[i]);
      if (next === 2 && !l2Allowed[i]) {
        // Over budget: fall back to the instanced representation.
        next = sr >= LOD_THRESHOLDS.L1_EXIT ? 1 : 0;
      }

      if (next !== levels[i]) {
        levels[i] = next;

        if (next === 2) {
          // Entering L2: create mesh if needed and fade it in.
          createL2Mesh(i, obj);
        }

        // L1 instance visibility based on next level (L2 handled by fade).
        if (rep && next === 1) {
          rep.instances.show(rep.localIndex, scratch, radii[i]);
        } else if (rep && next === 0) {
          rep.instances.hide(rep.localIndex);
        }
      } else if (next === 1 && obj.parent && rep) {
        // Keep a moving exoplanet's instance in sync while it is at L1.
        rep.instances.show(rep.localIndex, scratch, radii[i]);
      }

      // Animate the L2 crossfade. The target is "level 2 or pinned"; the pin is
      // dropped once normal LOD takes over, so the mesh is always released.
      const state = l2State.get(i);
      if (state) {
        if (levels[i] === 2) state.pinned = false;
        const shouldShow = levels[i] === 2 || state.pinned;
        // Keep the placeholder visible for the whole crossfade, then let
        // `destroyL2Mesh` hide it again.
        state.placeholder.visible = shouldShow || state.fade > 0;
        state.fadeDir = shouldShow ? +1 : -1;
        if (state.fadeDir === +1) {
          state.fade = Math.min(1, state.fade + 1 / FADE_FRAMES);
        } else {
          state.fade = Math.max(0, state.fade - 1 / FADE_FRAMES);
        }
        applyFade(state.mesh, state.fade);
        if (state.fade === 1) {
          // Fully faded in: hide the L1 instance.
          if (rep) rep.instances.hide(rep.localIndex);
        }
        if (state.fade === 0 && state.fadeDir === -1) {
          // Fully faded out: destroy the L2 mesh.
          destroyL2Mesh(i);
        }
      }
    }

    localPoints.commit();
    localInstances.commit();
    if (galaxyClusterObjs.length > 0) {
      galaxyClusterPoints.commit();
      galaxyClusterInstances.commit();
    }
  }

  /** Screen-space pick for objects currently drawn at any LOD level. */
  function pick(clientX, clientY) {
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
        best = { obj: allObjs[i], screenDistance, distance };
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
    // Destroy all L2 meshes first (copy the keys: destroyL2Mesh deletes them).
    for (const index of [...l2State.keys()]) {
      destroyL2Mesh(index);
    }
    group.remove(localPoints.object);
    for (const mesh of localInstances.meshes) group.remove(mesh);
    localPoints.dispose();
    localInstances.dispose();
    if (galaxyClusterObjs.length > 0 && galaxyGroup) {
      galaxyGroup.remove(galaxyClusterPoints.object);
      for (const mesh of galaxyClusterInstances.meshes) galaxyGroup.remove(mesh);
      galaxyClusterPoints.dispose();
      galaxyClusterInstances.dispose();
    }
  }

  // Establish the initial representation before the first frame is drawn.
  update();

  return {
    update,
    pick,
    counts,
    dispose,
    ensureL2,
    releaseL2,
    thresholds: LOD_THRESHOLDS,
    objectCount: count,
  };
}
