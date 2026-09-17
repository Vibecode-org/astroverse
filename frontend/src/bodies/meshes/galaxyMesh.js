import * as THREE from 'three';
import { makeSpiralGalaxyTexture } from '../textures/nebulaTextures';

export function createGalaxyMesh(obj) {
  const group = new THREE.Group();
  const radius = obj.radius || 1;
  
  // Для M104 (Sombrero Galaxy) создаем особую структуру
  if (obj.id === 'm104') {
    const core = new THREE.Mesh(
      new THREE.SphereGeometry(radius * 0.75, 32, 24),
      new THREE.MeshBasicMaterial({ color: 0xffeedd, transparent: true, opacity: 0.9 })
    );
    const ringTop = new THREE.Mesh(
      new THREE.RingGeometry(radius * 0.8, radius * 2.6, 64),
      new THREE.MeshBasicMaterial({ color: 0xeeddcc, side: THREE.DoubleSide, transparent: true, opacity: 0.85 })
    );
    const darkLane = new THREE.Mesh(
      new THREE.RingGeometry(radius * 0.82, radius * 1.05, 64),
      new THREE.MeshBasicMaterial({ color: 0x110e0a, side: THREE.DoubleSide })
    );
    ringTop.rotation.x = Math.PI / 2.05;
    darkLane.rotation.x = Math.PI / 2.05;
    group.add(core, ringTop, darkLane);
  } else {
    // Обычная спиральная галактика
    const galaxyTex = makeSpiralGalaxyTexture(obj.color || '#99ccff');
    const disk = new THREE.Mesh(
      new THREE.PlaneGeometry(radius * 5.5, radius * 5.5),
      new THREE.MeshBasicMaterial({
        map: galaxyTex,
        side: THREE.DoubleSide,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    disk.rotation.x = Math.PI / 2.6;
    group.add(disk);
  }
  
  obj.userData = { ...group };
  return group;
}