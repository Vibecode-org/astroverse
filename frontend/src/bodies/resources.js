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
// Textures that outlive a single scene (module-level caches). They must never
// be disposed by `disposeSceneResources`, or the next scene rebuild would use a
// texture whose GPU copy was already released.
const sharedTextures = new Set();

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
 * Shared textures are tracked separately: disposing a material never disposes
 * its maps, and a shared material is never disposed, so cached maps live as
 * long as the module that produced them.
 */
export function sharedTexture(key, build) {
  let texture = textures.get(key);
  if (!texture) {
    texture = build();
    textures.set(key, texture);
    sharedTextures.add(texture);
  }
  return texture;
}

/** Mark a texture as shared so scene teardown leaves it alone. */
export function registerSharedTexture(texture) {
  sharedTextures.add(texture);
  return texture;
}

const TEXTURE_SLOTS = [
  'map', 'alphaMap', 'emissiveMap', 'normalMap', 'roughnessMap', 'metalnessMap',
  'aoMap', 'envMap', 'bumpMap', 'displacementMap', 'specularMap', 'lightMap',
];

/** Dispose the per-object resources under `root`, leaving shared ones intact.
 *
 * Textures created for a single scene (labels, the Milky Way glow) are disposed
 * too; before this they leaked on every scene rebuild because only geometries
 * and materials were released.
 */
export function disposeSceneResources(root) {
  const ownedTextures = new Set();
  root.traverse((object) => {
    if (object.geometry && !shared.has(object.geometry)) object.geometry.dispose();
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    for (const material of materials) {
      if (!material) continue;
      for (const slot of TEXTURE_SLOTS) {
        const texture = material[slot];
        if (texture && !sharedTextures.has(texture)) ownedTextures.add(texture);
      }
      if (!shared.has(material)) material.dispose();
    }
  });
  for (const texture of ownedTextures) texture.dispose();
}
