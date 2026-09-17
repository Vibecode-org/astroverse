import * as THREE from 'three';
import { starPointTexture } from '../textures/starTextures.js';

export function makeOrbit(r, color = 0x242d42, opacity = 0.4) {
  const curve = new THREE.EllipseCurve(0, 0, r, r * 0.995, 0, Math.PI * 2, false, 0);
  const points = curve.getPoints(256).map((p) => new THREE.Vector3(p.x, 0, p.y));
  return new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity }),
  );
}

export function makeAsteroidBelt() {
  const group = new THREE.Group();
  const n = 1800;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const r = 24.5 + Math.random() * 8.5;
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = (Math.random() - 0.5) * 0.6;
    pos[i * 3 + 2] = Math.sin(a) * r;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  group.add(new THREE.Points(geo, new THREE.PointsMaterial({
    color: 0x8b8174,
    size: 0.09,
    map: starPointTexture,
    transparent: true,
    sizeAttenuation: true
  })));
  return group;
}

export function makeKuiperBelt() {
  const group = new THREE.Group();
  const n = 2400;
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const r = 168 + Math.random() * 70;
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = (Math.random() - 0.5) * 3.5;
    pos[i * 3 + 2] = Math.sin(a) * r;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  group.add(new THREE.Points(geo, new THREE.PointsMaterial({
    color: 0x6a7a99,
    size: 0.08,
    map: starPointTexture,
    transparent: true,
    opacity: 0.6
  })));
  return group;
}