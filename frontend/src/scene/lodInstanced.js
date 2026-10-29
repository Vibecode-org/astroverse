/** L1: one `InstancedMesh` per object kind.
 *
 * A single unit sphere is shared by every kind; the per-instance matrix carries
 * the object's real display radius. Colors come from the catalog, not from a
 * random hash, so an object keeps the same appearance at every LOD level.
 */

import * as THREE from 'three';
import { applyLimbDarkening } from '../bodies/meshes/starPlanetMesh.js';

const SPHERE_SEGMENTS = 16;
const SPHERE_RINGS = 12;

function makeSphere() {
  const geometry = new THREE.SphereGeometry(1, SPHERE_SEGMENTS, SPHERE_RINGS);
  // `vertexColors` needs a geometry color attribute. White keeps the result
  // equal to the per-instance color while still letting InstancedMesh multiply
  // it in the fragment shader.
  const count = geometry.attributes.position.count;
  geometry.setAttribute(
    'color',
    new THREE.BufferAttribute(new Float32Array(count * 3).fill(1), 3),
  );
  return geometry;
}

function makeMaterial(kind) {
  if (kind === 'star') {
    // Same limb darkening as the detailed star mesh: a flat `MeshBasicMaterial`
    // sphere reads as a paper disk once L1 grows past a few pixels.
    const material = new THREE.MeshBasicMaterial({ color: 0xffffff, vertexColors: true });
    applyLimbDarkening(material);
    return material;
  }
  return new THREE.MeshStandardMaterial({
    color: 0xffffff,
    vertexColors: true,
    roughness: 0.85,
    metalness: 0.05,
  });
}

export function createLODInstanced(objects) {
  const byKind = new Map();
  objects.forEach((obj, index) => {
    if (!byKind.has(obj.kind)) byKind.set(obj.kind, []);
    byKind.get(obj.kind).push({ obj, index });
  });

  const geometry = makeSphere();
  const zero = new THREE.Matrix4().makeScale(0, 0, 0);
  const matrix = new THREE.Matrix4();
  const color = new THREE.Color();

  const meshes = [];
  const byObject = new Array(objects.length).fill(null);
  const dirty = new Set();

  for (const [kind, entries] of byKind) {
    const material = makeMaterial(kind);
    const mesh = new THREE.InstancedMesh(geometry, material, entries.length);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    // The shared unit sphere's bounds do not describe scaled instances.
    mesh.frustumCulled = false;
    mesh.userData = { lodLevel: 1, kind, objectCount: entries.length };

    entries.forEach(({ obj, index }, localIndex) => {
      color.set(obj.color || '#ffffff');
      mesh.setColorAt(localIndex, color);
      mesh.setMatrixAt(localIndex, zero);
      byObject[index] = { mesh, localIndex };
    });
    mesh.instanceColor.needsUpdate = true;
    mesh.instanceMatrix.needsUpdate = true;

    meshes.push({ mesh, kind, material });
    dirty.add(mesh);
  }

  return {
    meshes: meshes.map((entry) => entry.mesh),

    /** Show one object as an L1 sphere with its real radius. */
    show(index, position, radius) {
      const slot = byObject[index];
      if (!slot) return;
      matrix.makeScale(radius, radius, radius);
      matrix.setPosition(position);
      slot.mesh.setMatrixAt(slot.localIndex, matrix);
      dirty.add(slot.mesh);
    },

    /** Hide one object's instance (it is rendered at L0 or L2 instead). */
    hide(index) {
      const slot = byObject[index];
      if (!slot) return;
      slot.mesh.setMatrixAt(slot.localIndex, zero);
      dirty.add(slot.mesh);
    },

    commit() {
      for (const mesh of dirty) mesh.instanceMatrix.needsUpdate = true;
      dirty.clear();
    },

    dispose() {
      geometry.dispose();
      for (const { material } of meshes) material.dispose();
    },
  };
}
