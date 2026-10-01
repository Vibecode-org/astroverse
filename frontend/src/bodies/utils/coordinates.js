import * as THREE from 'three';

/** Placement of catalog objects in the three viewing scales.
 *
 * These conversions are pure coordinate math, kept apart from the Milky Way
 * geometry so that positioning can be reasoned about (and reused) without
 * pulling in the 48k-point galaxy model.
 */

export const GALAXY_SCALE = 0.0058;
export const SUN_GALACTIC = { x: 78, y: 1.2, z: -18 };

/** Position from galactic coordinates, relative to the Sun's own location. */
export function galacticXYZ(obj) {
  if (obj.gx != null) return new THREE.Vector3(obj.gx, obj.gy || 0, obj.gz || 0);
  const l = ((obj.galactic_l || 0) * Math.PI) / 180;
  const b = ((obj.galactic_b || 0) * Math.PI) / 180;
  const r = (obj.distance_ly || 1000) * GALAXY_SCALE;
  return new THREE.Vector3(
    SUN_GALACTIC.x + r * Math.cos(b) * Math.cos(l),
    SUN_GALACTIC.y + r * Math.sin(b),
    SUN_GALACTIC.z + r * Math.cos(b) * Math.sin(l),
  );
}

/** Position from equatorial coordinates.
 *
 * The radius is compressed hard: the catalog spans thousands of light years, so
 * a linear mapping would bury everything but the nearest stars. Inside ~40 ly
 * the scale is linear, beyond that it grows logarithmically.
 */
export function equatorialXYZ(obj, scale = 0.9) {
  const ra = ((obj.ra || 0) * 15 * Math.PI) / 180;
  const dec = ((obj.dec || 0) * Math.PI) / 180;
  const dist = Math.max(obj.distance_ly || 4, 0.1);
  const r = Math.min(dist, 40) * scale + Math.max(0, Math.log10(dist / 40 + 1)) * 18;
  return new THREE.Vector3(
    r * Math.cos(dec) * Math.cos(ra),
    r * Math.sin(dec),
    r * Math.cos(dec) * Math.sin(ra),
  );
}
