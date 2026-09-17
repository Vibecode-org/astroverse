import * as THREE from 'three';
import { getTexture, makeRingTexture } from '../../textures.js';
import { makeStarCorona } from '../textures/starTextures';

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
  
  const map = getTexture(texName);
  
  const material = isStar
    ? new THREE.MeshBasicMaterial({ color: 0xffffff, map })
    : new THREE.MeshStandardMaterial({
      color: 0xffffff,
      map,
      roughness: ['jupiter', 'saturn', 'uranus', 'neptune'].includes(obj.texture) ? 0.5 : 0.8,
      metalness: 0.05,
    });
  
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 40, 28), material);
  mesh.userData = obj;
  if (obj.tilt) mesh.rotation.z = (obj.tilt * Math.PI) / 180;
  
  if (isStar) {
    mesh.add(makeStarCorona(obj.color || '#ffb74d', radius * 3.6));
  }
  
  if (obj.id === 'earth') {
    const atm = new THREE.Mesh(
      new THREE.SphereGeometry(radius * 1.015, 36, 24),
      new THREE.MeshStandardMaterial({ color: 0x4aa3ff, transparent: true, opacity: 0.2, roughness: 1.0 })
    );
    mesh.add(atm);
  }
  
  if (obj.rings) {
    const inner = radius * (obj.rings.inner || 1.35);
    const outer = radius * (obj.rings.outer || 2.35);
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(inner, outer, 96, 4),
      new THREE.MeshStandardMaterial({
        map: makeRingTexture(),
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.9,
        roughness: 0.6,
      })
    );
    ring.rotation.x = Math.PI / 2;
    mesh.add(ring);
  }
  
  return mesh;
}