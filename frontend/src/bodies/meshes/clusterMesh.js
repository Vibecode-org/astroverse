import * as THREE from 'three';
import { makeNebulaCloudSprite } from '../textures/nebulaTextures.js';

export function createClusterMesh(obj) {
  const group = new THREE.Group();
  const radius = obj.radius || 1;
  
  // Для Плеяд (M45) создаем особую структуру
  if (obj.id === 'm45' || obj.id === 'pleiades') {
    const stars = [[0.15,0.05,0], [-0.35,0.25,0.1], [-0.65,-0.2,-0.1], [-0.12,0.45,0], [-0.25,-0.42,0.1], [-0.52,0.32,-0.1], [0.35,0.12,0]];
    const starPos = new Float32Array(stars.length * 3);
    stars.forEach((s, idx) => {
      const x = s[0] * radius * 1.5; const y = s[1] * radius * 1.5; const z = s[2] * radius * 1.5;
      starPos[idx * 3] = x; starPos[idx * 3 + 1] = y; starPos[idx * 3 + 2] = z;
    });
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    group.add(new THREE.Points(starGeo, new THREE.PointsMaterial({
      size: 1.8, color: 0xeef8ff, map: null, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    })));
    
    // Туманность вокруг
    const haze = makeNebulaCloudSprite('#3388ff', radius * 1.2);
    group.add(haze);
  } else {
    // Обычное звездное скопление
    const count = 280;
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    const baseCol = new THREE.Color(obj.color || '#ffe0a8');

    for (let i = 0; i < count; i++) {
      const u = Math.random();
      const r = radius * (Math.pow(u, 2.8) * 1.1 + 0.06);
      const theta = Math.random() * Math.PI * 2;
      const phi = (Math.random() - 0.5) * Math.PI;

      pos[i * 3] = r * Math.cos(phi) * Math.cos(theta);
      pos[i * 3 + 1] = r * Math.sin(phi);
      pos[i * 3 + 2] = r * Math.cos(phi) * Math.sin(theta);

      const isBlue = Math.random() < 0.08;
      const starCol = isBlue
        ? new THREE.Color('#99bbff')
        : baseCol.clone().offsetHSL((Math.random() - 0.5) * 0.05, 0, (Math.random() - 0.5) * 0.2);

      col[i * 3] = starCol.r;
      col[i * 3 + 1] = starCol.g;
      col[i * 3 + 2] = starCol.b;
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
    group.add(new THREE.Points(geo, new THREE.PointsMaterial({
      size: 0.9, map: null, vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    })));

    group.add(makeNebulaCloudSprite(obj.color || '#ffe0a8', radius * 1.2));
  }
  
  obj.userData = { ...group };
  return group;
}