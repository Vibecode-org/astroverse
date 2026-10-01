import * as THREE from 'three';
import { makeSpiralGalaxyTexture } from '../textures/nebulaTextures.js';
import { sharedGeometry, sharedMaterial } from '../resources.js';
import { safeColor } from '../utils/colorUtils.js';

function sombreroCore(radius) {
  const geometry = sharedGeometry(`m104:core:${radius}`, () => new THREE.SphereGeometry(radius * 0.75, 32, 24));
  const material = sharedMaterial('m104:core', () => new THREE.MeshBasicMaterial({
    color: 0xffeedd,
    transparent: true,
    opacity: 0.9,
  }));
  return new THREE.Mesh(geometry, material);
}

function sombreroRing(radius, inner, outer, key, color, opacity) {
  const geometry = sharedGeometry(`m104:${key}:${radius}`, () => new THREE.RingGeometry(radius * inner, radius * outer, 64));
  const material = sharedMaterial(`m104:${key}`, () => new THREE.MeshBasicMaterial({
    color,
    side: THREE.DoubleSide,
    transparent: opacity < 1,
    opacity,
  }));
  const ring = new THREE.Mesh(geometry, material);
  ring.rotation.x = Math.PI / 2.05;
  return ring;
}

function spiralDisk(radius, color) {
  const map = makeSpiralGalaxyTexture(color);
  const geometry = sharedGeometry(`galaxy:disk:${radius}`, () => new THREE.PlaneGeometry(radius * 5.5, radius * 5.5));
  const material = sharedMaterial(`galaxy:disk:${color}`, () => new THREE.MeshBasicMaterial({
    map,
    side: THREE.DoubleSide,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }));
  const disk = new THREE.Mesh(geometry, material);
  disk.rotation.x = Math.PI / 2.6;
  return disk;
}

export function createGalaxyMesh(obj) {
  const group = new THREE.Group();
  const radius = obj.radius || 1;

  // Для M104 (Sombrero Galaxy) создаем особую структуру
  if (obj.id === 'm104') {
    group.add(sombreroCore(radius));
    group.add(sombreroRing(radius, 0.8, 2.6, 'ring', 0xeeddcc, 0.85));
    group.add(sombreroRing(radius, 0.82, 1.05, 'lane', 0x110e0a, 1));
  } else {
    // Обычная спиральная галактика
    group.add(spiralDisk(radius, safeColor(obj.color, '#99ccff')));
  }

  group.userData = obj;
  return group;
}
