/** Own detailed legacy L2 meshes, cloned fade materials and selection pins.
 * The controller owns level decisions and advances fades; shared body resources
 * remain owned by bodies/resources.js.
 */
import { createBodyMesh } from '../bodies/index.js';
import { disposeSceneResources } from '../bodies/resources.js';

export function createL2Meshes({ meshes, indexById }) {
  const l2State = new Map();

  /** Create the detailed L2 mesh for object at `index`, attach it to the
   *  placeholder and start fading it in. */
  function createL2Mesh(index, obj) {
    const placeholder = meshes.get(obj.id);
    if (!placeholder) return null;

    // Don't recreate if an L2 mesh already exists for this object.
    if (l2State.has(index)) return l2State.get(index).mesh;

    const mesh = createBodyMesh(obj);
    mesh.userData.lodLevel = 2;
    // Clone the material so we can fade opacity without touching shared
    // resources. The clone is not shared and will be disposed with the mesh.
    if (mesh.material) {
      const original = mesh.material;
      mesh.material = original.clone();
      mesh.material.opacity = 0;
      mesh.material.transparent = true;
    }
    // Traverse children (corona, rings, atmosphere) and clone their materials too.
    mesh.traverse((child) => {
      if (child.material && child.material !== mesh.material) {
        const orig = child.material;
        child.material = orig.clone();
        child.material.opacity = 0;
        child.material.transparent = true;
      }
    });

    placeholder.add(mesh);
    placeholder.visible = true;
    mesh.position.set(0, 0, 0);
    placeholder.updateMatrixWorld();

    // Disable frustum culling: the placeholder has no geometry/bounds, so
    // Three.js may cull the L2 mesh (child) incorrectly.
    mesh.frustumCulled = false;

    l2State.set(index, { mesh, placeholder, fade: 0, fadeDir: +1 });
    mesh.visible = true;
    return mesh;
  }

  /** Destroy the L2 mesh for object at `index`, freeing per-object resources.
   *  Shared geometries/materials from bodies/resources.js are never disposed. */
  function destroyL2Mesh(index) {
    const state = l2State.get(index);
    if (!state) return;
    const { mesh, placeholder } = state;
    if (mesh && placeholder) {
      placeholder.remove(mesh);
      disposeSceneResources(mesh);
      // Nothing is drawn through the placeholder any more.
      placeholder.visible = false;
    }
    l2State.delete(index);
  }

  /** Ensure an L2 mesh exists for `obj` (e.g. when selected from the list).
   *  Pins it so it stays visible while the camera is still far away. The pin is
   *  released when another object is selected, when the selection is cleared,
   *  or as soon as the object reaches L2 through normal LOD.
   *  Returns the mesh or null if the object is not in the LOD set. */
  function ensureL2(obj) {
    const index = indexById.get(obj.id);
    if (index === undefined) return null;

    // Only one object can be pinned at a time; otherwise every selected object
    // would keep its detailed mesh (and its cloned materials) forever.
    for (const [otherIndex, other] of l2State) {
      if (otherIndex !== index) other.pinned = false;
    }

    const state = l2State.get(index);
    if (state) {
      state.pinned = true;
      state.fade = 1;
      state.fadeDir = +1;
      applyFade(state.mesh, 1);
      state.mesh.visible = true;
      state.placeholder.visible = true;
      return state.mesh;
    }
    const mesh = createL2Mesh(index, obj);
    const newState = l2State.get(index);
    if (newState) {
      newState.pinned = true;
      newState.fade = 1;
      newState.fadeDir = +1;
      applyFade(newState.mesh, 1);
      newState.mesh.visible = true;
    }
    return mesh;
  }

  /** Drop every L2 pin (called when the selection is cleared). Meshes that are
   *  not at L2 fade out and are disposed by `update`. */
  function releaseL2() {
    for (const state of l2State.values()) state.pinned = false;
  }

  /** Apply opacity fade to an L2 mesh and all its children. */
  function applyFade(mesh, opacity) {
    if (mesh.material) mesh.material.opacity = opacity;
    mesh.traverse((child) => {
      if (child.material) child.material.opacity = opacity;
    });
  }

  return {
    states: l2State, create: createL2Mesh, destroy: destroyL2Mesh,
    ensure: ensureL2, release: releaseL2, applyFade,
  };
}
