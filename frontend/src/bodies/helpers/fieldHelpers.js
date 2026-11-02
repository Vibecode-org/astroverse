import * as THREE from 'three';
import { starPointTexture } from '../textures/starTextures.js';
import { makeSeededRng } from '../utils/rng.js';

export function makeStarField(count, radius) {
  const geo = new THREE.BufferGeometry();
  const arr = new Float32Array(count * 3);
  const col = new Float32Array(count * 3);
  // Deterministic star field: the same catalog always renders the same sky.
  const rng = makeSeededRng(`starfield:${count}:${radius}`);
  for (let i = 0; i < count; i++) {
    const r = radius * (0.35 + rng() * 0.65);
    const a = rng() * Math.PI * 2;
    const y = (rng() - 0.5) * radius * 0.3;
    arr[i * 3] = Math.cos(a) * r;
    arr[i * 3 + 1] = y;
    arr[i * 3 + 2] = Math.sin(a) * r;
    const t = rng();
    if (t > 0.8) { col[i * 3] = 0.75; col[i * 3 + 1] = 0.88; col[i * 3 + 2] = 1; }
    else if (t < 0.15) { col[i * 3] = 1; col[i * 3 + 1] = 0.82; col[i * 3 + 2] = 0.6; }
    else { col[i * 3] = 0.95; col[i * 3 + 1] = 0.95; col[i * 3 + 2] = 1; }
  }
  geo.setAttribute('position', new THREE.BufferAttribute(arr, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  return new THREE.Points(geo, new THREE.PointsMaterial({
    size: 1.4,
    map: starPointTexture,
    sizeAttenuation: false,
    vertexColors: true,
    transparent: true,
  }));
}