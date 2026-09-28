import * as THREE from 'three';
import { getTexture, makeRingTexture } from '../../textures.js';
import { makeStarCorona } from '../textures/starTextures.js';
import { sharedGeometry, sharedMaterial } from '../resources.js';

const SHELL_SEGMENTS = 40;
const SHELL_RINGS = 28;
const ATMOSPHERE_SEGMENTS = 36;
const ATMOSPHERE_RINGS = 24;
const RING_SEGMENTS = 96;
const GAS_GIANTS = ['jupiter', 'saturn', 'uranus', 'neptune'];

/** The catalog reuses a few dozen distinct radii, so shells are cached by radius
 * instead of allocating ~140 KB of vertices for every one of 3.2k bodies. */
function shellGeometry(radius) {
  return sharedGeometry(`shell:${radius}`, () =>
    new THREE.SphereGeometry(radius, SHELL_SEGMENTS, SHELL_RINGS));
}

function shellMaterial(isStar, texName, smooth) {
  const map = getTexture(texName);
  return sharedMaterial(`shell:${isStar}:${texName}:${smooth}`, () => (isStar
    ? new THREE.MeshBasicMaterial({ color: 0xffffff, map })
    : new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map,
      roughness: smooth ? 0.5 : 0.8,
      metalness: 0.05,
    })));
}

function atmosphereMesh(radius) {
  const geometry = sharedGeometry(`atmosphere:${radius}`, () =>
    new THREE.SphereGeometry(radius * 1.015, ATMOSPHERE_SEGMENTS, ATMOSPHERE_RINGS));
  const material = sharedMaterial('atmosphere', () => new THREE.MeshStandardMaterial({
    color: 0x4aa3ff,
    transparent: true,
    opacity: 0.2,
    roughness: 1.0,
  }));
  return new THREE.Mesh(geometry, material);
}

function ringMesh(radius, rings) {
  const inner = radius * (rings.inner || 1.35);
  const outer = radius * (rings.outer || 2.35);
  const geometry = sharedGeometry(`ring:${inner}:${outer}`, () =>
    new THREE.RingGeometry(inner, outer, RING_SEGMENTS, 4));
  const material = sharedMaterial('ring', () => new THREE.MeshStandardMaterial({
    map: makeRingTexture(),
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.9,
    roughness: 0.6,
  }));
  const ring = new THREE.Mesh(geometry, material);
  ring.rotation.x = Math.PI / 2;
  return ring;
}

export function createStarPlanetMesh(obj) {
  const radius = obj.id === 'phobos' ? 0.038 : obj.id === 'deimos' ? 0.026 : (obj.radius || 0.4);
  const isStar = obj.kind === 'star';

  // Определяем текстуру
  let texName = obj.texture;
  if (isStar) {
    const t = obj.temperature_k || 5500;
    texName = t > 8500 ? 'star_blue' : t > 7000 ? 'star_white' : t > 5200 ? 'star_yellow' : t > 3700 ? 'star_orange' : 'star_red';
  } else if (!texName) {
    if (obj.kind === 'exoplanet') {
      const t = obj.temperature_k || 300;
      texName = t > 500 ? 'exoplanet_lava' : 'exoplanet_habitable';
    } else {
      texName = 'rocky';
    }
  }

  const mesh = new THREE.Mesh(shellGeometry(radius), shellMaterial(isStar, texName, GAS_GIANTS.includes(obj.texture)));
  mesh.userData = obj;
  if (obj.tilt) mesh.rotation.z = (obj.tilt * Math.PI) / 180;

  if (isStar) {
    mesh.add(makeStarCorona(obj.color || '#ffb74d', radius * 3.6));
  }

  if (obj.id === 'earth') {
    mesh.add(atmosphereMesh(radius));
  }

  if (obj.rings) {
    mesh.add(ringMesh(radius, obj.rings));
  }

  return mesh;
}
