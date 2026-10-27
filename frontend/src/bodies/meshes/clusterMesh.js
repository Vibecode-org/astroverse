import * as THREE from 'three';
import { makeNebulaCloudSprite } from '../textures/nebulaTextures.js';
import { sharedGeometry, sharedMaterial } from '../resources.js';
import { safeColor } from '../utils/colorUtils.js';
import { hashUnit } from '../utils/hash.js';

const PLEIADES_STARS = [[0.15,0.05,0], [-0.35,0.25,0.1], [-0.65,-0.2,-0.1], [-0.12,0.45,0], [-0.25,-0.42,0.1], [-0.52,0.32,-0.1], [0.35,0.12,0]];
const CLUSTER_STARS = 280;

/** Pleiades outline in unit radius; the caller scales the whole field. */
function pleiadesGeometry() {
  return sharedGeometry('cluster:pleiades', () => {
    const positions = new Float32Array(PLEIADES_STARS.length * 3);
    PLEIADES_STARS.forEach((star, index) => {
      positions[index * 3] = star[0] * 1.5;
      positions[index * 3 + 1] = star[1] * 1.5;
      positions[index * 3 + 2] = star[2] * 1.5;
    });
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    return geometry;
  });
}

function pleiadesMaterial() {
  return sharedMaterial('cluster:pleiades', () => new THREE.PointsMaterial({
    size: 1.8,
    color: 0xeef8ff,
    map: null,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }));
}

/** Generic cluster field in unit radius. Kept per object on purpose: sharing it
 * by color would make every cluster render the same star pattern. The memory is
 * negligible next to the body shells, so visual variety wins. */
function clusterGeometry(colorHex, seed) {
  const positions = new Float32Array(CLUSTER_STARS * 3);
  const colors = new Float32Array(CLUSTER_STARS * 3);
  const baseCol = new THREE.Color(safeColor(colorHex, '#ffe0a8'));
  const scratch = new THREE.Color();

  // Deterministic RNG from seed (object id)
  let rngState = 0;
  function nextRandom() {
    rngState = (rngState * 1664525 + 1013904223) >>> 0;
    return rngState / 4294967296;
  }
  // Initialize RNG state from seed
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  rngState = h >>> 0;

  for (let i = 0; i < CLUSTER_STARS; i++) {
    const r = Math.pow(nextRandom(), 2.8) * 1.1 + 0.06;
    const theta = nextRandom() * Math.PI * 2;
    const phi = (nextRandom() - 0.5) * Math.PI;

    positions[i * 3] = r * Math.cos(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi);
    positions[i * 3 + 2] = r * Math.cos(phi) * Math.sin(theta);

    const starCol = nextRandom() < 0.08
      ? scratch.set('#99bbff')
      : scratch.copy(baseCol).offsetHSL((nextRandom() - 0.5) * 0.05, 0, (nextRandom() - 0.5) * 0.2);

    colors[i * 3] = starCol.r;
    colors[i * 3 + 1] = starCol.g;
    colors[i * 3 + 2] = starCol.b;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  return geometry;
}

function clusterMaterial() {
  return sharedMaterial('cluster:field', () => new THREE.PointsMaterial({
    size: 0.9,
    map: null,
    vertexColors: true,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }));
}

export function createClusterMesh(obj) {
  const group = new THREE.Group();
  const radius = obj.radius || 1;

  // Для Плеяд (M45) создаем особую структуру
  if (obj.id === 'm45' || obj.id === 'pleiades') {
    const stars = new THREE.Points(pleiadesGeometry(), pleiadesMaterial());
    stars.scale.setScalar(radius);
    group.add(stars);
    // Туманность вокруг
    group.add(makeNebulaCloudSprite('#3388ff', radius * 1.2));
  } else {
    // Обычное звездное скопление
    const color = safeColor(obj.color, '#ffe0a8');
    const field = new THREE.Points(clusterGeometry(color, obj.id), clusterMaterial());
    field.scale.setScalar(radius);
    group.add(field);
    group.add(makeNebulaCloudSprite(color, radius * 1.2));
  }

  group.userData = obj;
  return group;
}
