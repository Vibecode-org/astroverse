import * as THREE from 'three';
import { makeAccretionDiskTexture, makePhotonRingTexture } from '../textures/nebulaTextures.js';
import { makeStarCorona } from '../textures/starTextures.js';

export function createBlackHoleMesh(obj) {
  const radius = obj.radius || 1;
  const group = new THREE.Group();

  // Чёрная дыра с аккреционным диском
  const disk = new THREE.Mesh(
    new THREE.RingGeometry(radius * 1.15, radius * 4.4, 96, 16),
    new THREE.MeshBasicMaterial({
      map: makeAccretionDiskTexture(0.32),
      side: THREE.DoubleSide,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  disk.rotation.x = Math.PI / 2.2;
  disk.rotation.y = 0.15;
  group.add(disk);

  // Фотонная корона
  const photonRing = new THREE.Mesh(
    new THREE.RingGeometry(radius * 1.01, radius * 1.15, 96),
    new THREE.MeshBasicMaterial({
      map: makePhotonRingTexture(),
      side: THREE.DoubleSide,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  group.add(photonRing);

  // Линза гравитационного эффекта
  const lensHalo = new THREE.Mesh(
    new THREE.RingGeometry(radius * 1.15, radius * 3.4, 96, 16),
    new THREE.MeshBasicMaterial({
      map: makeAccretionDiskTexture(0.42),
      side: THREE.DoubleSide,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    })
  );
  lensHalo.rotation.y = Math.PI / 2.3;
  group.add(lensHalo);

  // Полярные релятивистские джеты (для M87* и Лебедя X-1)
  if (obj.has_jet) {
    const jetGeo = new THREE.ConeGeometry(radius * 0.35, radius * 9.0, 32, 1, true);
    const jetMat = new THREE.MeshBasicMaterial({
      color: 0x55ccff,
      transparent: true,
      opacity: 0.65,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    });
    const jetNorth = new THREE.Mesh(jetGeo, jetMat);
    jetNorth.position.y = radius * 4.5;
    const jetSouth = new THREE.Mesh(jetGeo, jetMat);
    jetSouth.position.y = -radius * 4.5;
    jetSouth.rotation.z = Math.PI;
    group.add(jetNorth, jetSouth);
  }

  group.add(makeStarCorona(obj.color || '#ff8833', radius * 4.8));
  group.userData = { ...obj, isBlackHole: true, disk, lensHalo, photonRing };
  return group;
}