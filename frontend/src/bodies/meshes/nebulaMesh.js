import * as THREE from 'three';
import { makeNebulaCloudSprite } from '../textures/nebulaTextures.js';

export function createNebulaMesh(obj) {
  const group = new THREE.Group();
  
  // Основная туманность
  const nebula = new THREE.Mesh(
    new THREE.SphereGeometry(obj.radius || 1, 32, 32),
    new THREE.MeshBasicMaterial({
      color: 0xff8cb0,
      transparent: true,
      opacity: 0.8,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  group.add(nebula);
  
  // Облака туманности
  for (let i = 0; i < 3; i++) {
    const cloud = makeNebulaCloudSprite(obj.color || '#ff8cb0', (obj.radius || 1) * (2.6 + i * 0.7));
    cloud.position.set(
      (Math.random() - 0.5) * (obj.radius || 1) * 0.4,
      (Math.random() - 0.5) * (obj.radius || 1) * 0.3,
      0
    );
    group.add(cloud);
  }
  
  obj.userData = { ...group };
  return group;
}