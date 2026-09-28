import * as THREE from 'three';
import { makeNebulaCloudSprite } from '../textures/nebulaTextures.js';
import { sharedGeometry, sharedMaterial } from '../resources.js';

const SHELL_SEGMENTS = 32;

function shellGeometry(radius) {
  return sharedGeometry(`nebula:${radius}`, () => new THREE.SphereGeometry(radius, SHELL_SEGMENTS, SHELL_SEGMENTS));
}

function shellMaterial() {
  return sharedMaterial('nebula', () => new THREE.MeshBasicMaterial({
    color: 0xff8cb0,
    transparent: true,
    opacity: 0.8,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }));
}

export function createNebulaMesh(obj) {
  const group = new THREE.Group();
  const radius = obj.radius || 1;

  // Основная туманность
  group.add(new THREE.Mesh(shellGeometry(radius), shellMaterial()));

  // Облака туманности
  for (let i = 0; i < 3; i++) {
    const cloud = makeNebulaCloudSprite(obj.color || '#ff8cb0', radius * (2.6 + i * 0.7));
    cloud.position.set(
      (Math.random() - 0.5) * radius * 0.4,
      (Math.random() - 0.5) * radius * 0.3,
      0
    );
    group.add(cloud);
  }

  group.userData = obj;
  return group;
}
