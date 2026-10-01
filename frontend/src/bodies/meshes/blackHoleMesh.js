import * as THREE from 'three';
import { makeAccretionDiskTexture, makePhotonRingTexture } from '../textures/nebulaTextures.js';
import { makeStarCorona } from '../textures/starTextures.js';
import { sharedGeometry, sharedMaterial } from '../resources.js';
import { safeColor } from '../utils/colorUtils.js';

const DISK_SEGMENTS = 96;
const DISK_RINGS = 16;
const JET_SEGMENTS = 32;

function radialGeometry(key, radius, inner, outer, rings) {
  return sharedGeometry(`bh:${key}:${radius}`, () =>
    new THREE.RingGeometry(radius * inner, radius * outer, DISK_SEGMENTS, rings));
}

function diskMaterial(ratio) {
  const map = makeAccretionDiskTexture(ratio);
  return sharedMaterial(`bh:disk:${ratio}`, () => new THREE.MeshBasicMaterial({
    map,
    side: THREE.DoubleSide,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }));
}

function photonRingMaterial() {
  return sharedMaterial('bh:photon', () => new THREE.MeshBasicMaterial({
    map: makePhotonRingTexture(),
    side: THREE.DoubleSide,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }));
}

function jetMaterial() {
  return sharedMaterial('bh:jet', () => new THREE.MeshBasicMaterial({
    color: 0x55ccff,
    transparent: true,
    opacity: 0.65,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  }));
}

export function createBlackHoleMesh(obj) {
  const radius = obj.radius || 1;
  const group = new THREE.Group();

  // Чёрная дыра с аккреционным диском
  const disk = new THREE.Mesh(radialGeometry('disk', radius, 1.15, 4.4, DISK_RINGS), diskMaterial(0.32));
  disk.rotation.x = Math.PI / 2.2;
  disk.rotation.y = 0.15;
  group.add(disk);

  // Фотонная корона
  const photonRing = new THREE.Mesh(radialGeometry('photon', radius, 1.01, 1.15, 0), photonRingMaterial());
  group.add(photonRing);

  // Линза гравитационного эффекта
  const lensHalo = new THREE.Mesh(radialGeometry('lens', radius, 1.15, 3.4, DISK_RINGS), diskMaterial(0.42));
  lensHalo.rotation.y = Math.PI / 2.3;
  group.add(lensHalo);

  // Полярные релятивистские джеты (для M87* и Лебедя X-1)
  if (obj.has_jet) {
    const jetGeo = sharedGeometry(`bh:jet:${radius}`, () =>
      new THREE.ConeGeometry(radius * 0.35, radius * 9.0, JET_SEGMENTS, 1, true));
    const jetMat = jetMaterial();
    const jetNorth = new THREE.Mesh(jetGeo, jetMat);
    jetNorth.position.y = radius * 4.5;
    const jetSouth = new THREE.Mesh(jetGeo, jetMat);
    jetSouth.position.y = -radius * 4.5;
    jetSouth.rotation.z = Math.PI;
    group.add(jetNorth, jetSouth);
  }

  group.add(makeStarCorona(safeColor(obj.color, '#ff8833'), radius * 4.8));
  // The render loop reads the animated sub-meshes back out of userData.
  group.userData = { ...obj, isBlackHole: true, disk, lensHalo, photonRing };
  return group;
}
