/** Pure LOD selection rules for the deep-sky layer.
 *
 * Levels are chosen from the object's projected radius in pixels:
 *   L0 — a point in the shared `Points` cloud (far)
 *   L1 — an instance in the per-kind `InstancedMesh` (mid)
 *   L2 — the existing detailed mesh (near, selected or followed)
 *
 * Thresholds use hysteresis: entering a level needs a larger radius than
 * leaving it. Without that, an object sitting exactly on a threshold would
 * flicker between two representations on every camera nudge.
 */

export const LOD_THRESHOLDS = {
  L1_ENTER: 3.0,
  L1_EXIT: 2.0,
  L2_ENTER: 12.0,
  L2_EXIT: 8.0,
};

/** Next level for a projected radius, given the current level (-1 = unknown). */
export function lodLevel(screenRadius, previous) {
  if (previous === 2) {
    if (screenRadius >= LOD_THRESHOLDS.L2_EXIT) return 2;
    if (screenRadius >= LOD_THRESHOLDS.L1_EXIT) return 1;
    return 0;
  }

  if (previous === 1) {
    if (screenRadius >= LOD_THRESHOLDS.L2_ENTER) return 2;
    if (screenRadius >= LOD_THRESHOLDS.L1_EXIT) return 1;
    return 0;
  }

  if (screenRadius >= LOD_THRESHOLDS.L2_ENTER) return 2;
  if (screenRadius >= LOD_THRESHOLDS.L1_ENTER) return 1;
  return 0;
}

/** Projected radius in pixels for a sphere of `radius` at `distance`. */
export function screenRadius(radius, distance, focalLength) {
  return (radius / Math.max(distance, 1e-4)) * focalLength;
}

/** Focal length in pixels for a perspective camera and a viewport height. */
export function focalLength(camera, height) {
  const fov = (camera.fov * Math.PI) / 180;
  return height / 2 / Math.tan(fov / 2);
}
