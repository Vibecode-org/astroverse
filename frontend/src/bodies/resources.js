/** Reusable GPU resources for the whole catalog.
 *
 * The catalog holds a few thousand objects, but they collapse onto a few dozen
 * distinct geometries, materials and textures. Everything here is built once,
 * keyed by value, and shared: a shared resource outlives any single scene, so
 * callers must never mutate it and must never dispose it per object.
 */

const shared = new Set();
const geometries = new Map();
const materials = new Map();
const textures = new Map();

/** Reuse the geometry stored under `key`, or build, remember and store it. */
export function sharedGeometry(key, build) {
  let geometry = geometries.get(key);
  if (!geometry) {
    geometry = build();
    geometries.set(key, geometry);
    shared.add(geometry);
  }
  return geometry;
}

/** Reuse the material stored under `key`, or build, remember and store it. */
export function sharedMaterial(key, build) {
  let material = materials.get(key);
  if (!material) {
    material = build();
    materials.set(key, material);
    shared.add(material);
  }
  return material;
}

/** Reuse the texture stored under `key`, or build and store it.
 *
 * Textures are not tracked in `shared`: disposing a material never disposes its
 * maps, and a shared material is never disposed, so cached maps live as long as
 * the module that produced them.
 */
export function sharedTexture(key, build) {
  let texture = textures.get(key);
  if (!texture) {
    texture = build();
    textures.set(key, texture);
  }
  return texture;
}

/** Dispose the per-object resources under `root`, leaving shared ones intact. */
export function disposeSceneResources(root) {
  root.traverse((object) => {
    if (object.geometry && !shared.has(object.geometry)) object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      if (material && !shared.has(material)) material.dispose();
    }
  });
}
