import * as THREE from 'three';
import { starPointTexture } from '../textures/starTextures.js';
import { SUN_GALACTIC } from '../utils/coordinates.js';

/** The Milky Way model: an edge-on barred spiral rendered as point clouds.
 *
 * Every random draw goes through the seeded generator below, so the galaxy is
 * byte-for-byte identical on each scene rebuild — a `Math.random()` here would
 * make the whole sky shimmer on every re-mount.
 */

function rng(seed) {
  return function () {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function addPoints(group, positions, colors, opts) {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  const mat = new THREE.PointsMaterial({
    size: opts.size,
    map: starPointTexture,
    vertexColors: true,
    transparent: true,
    opacity: opts.opacity,
    depthWrite: false,
    blending: opts.additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    sizeAttenuation: true,
  });
  group.add(new THREE.Points(geo, mat));
}

/** Build the star field: bulge, four spiral arms plus the Orion Spur, halo. */
function addStarField(group, rand) {
  const starCount = 48000;
  const pos = new Float32Array(starCount * 3);
  const col = new Float32Array(starCount * 3);

  const arms = [
    { offset: 0.18, pitch: 0.23, weight: 1 },
    { offset: Math.PI / 2 + 0.12, pitch: 0.23, weight: 1 },
    { offset: Math.PI + 0.04, pitch: 0.22, weight: 0.9 },
    { offset: (3 * Math.PI) / 2 - 0.1, pitch: 0.225, weight: 0.95 },
    { offset: 2.55, pitch: 0.32, weight: 0.28 },
  ];

  let i = 0;
  // Просвет в самом центре для Стрельца A* (r начинается с 4.5)
  const bulge = 7000;
  for (; i < bulge; i++) {
    const a = rand() * Math.PI * 2;
    const r = 4.5 + Math.pow(rand(), 0.6) * 18;
    const y = (rand() - 0.5) * (10 - r * 0.2);
    pos[i * 3] = Math.cos(a) * r * (0.55 + Math.abs(Math.cos(a)) * 0.7);
    pos[i * 3 + 1] = y;
    pos[i * 3 + 2] = Math.sin(a) * r * 0.62;
    const t = rand();
    col[i * 3] = 1.0;
    col[i * 3 + 1] = 0.85 + t * 0.1;
    col[i * 3 + 2] = 0.6 + t * 0.15;
  }

  // Спиральные рукава
  for (; i < starCount - 4000; i++) {
    const arm = arms[Math.floor(rand() * arms.length)];
    const theta = rand() * 6.4;
    let radius = 18 * Math.exp(arm.pitch * theta);
    if (arm.weight < 0.4) radius = 58 + rand() * 28;
    radius *= 0.85 + rand() * 0.08;
    if (radius > 148) {
      i--;
      continue;
    }
    const angle = theta + arm.offset;
    const spread = (rand() - 0.5) * (1.6 + radius * 0.045) / (arm.weight + 0.2);
    const x = Math.cos(angle) * radius + spread;
    const z = Math.sin(angle) * radius + spread;
    const diskH = (2.2 + (150 - radius) * 0.012) * (rand() - 0.5);
    pos[i * 3] = x;
    pos[i * 3 + 1] = diskH;
    pos[i * 3 + 2] = z;

    const young = rand() < 0.35 && radius > 40;
    if (young) {
      col[i * 3] = 0.72 + rand() * 0.2;
      col[i * 3 + 1] = 0.82 + rand() * 0.15;
      col[i * 3 + 2] = 1.0;
    } else if (radius < 36) {
      col[i * 3] = 1.0;
      col[i * 3 + 1] = 0.88;
      col[i * 3 + 2] = 0.65;
    } else {
      const t = rand();
      col[i * 3] = 0.95 + t * 0.05;
      col[i * 3 + 1] = 0.9 + t * 0.08;
      col[i * 3 + 2] = 0.82 + t * 0.15;
    }
  }

  // Внешнее гало
  for (; i < starCount; i++) {
    const a = rand() * Math.PI * 2;
    const r = 20 + Math.pow(rand(), 0.35) * 170;
    const y = (rand() - 0.5) * 80;
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = y;
    pos[i * 3 + 2] = Math.sin(a) * r;
    col[i * 3] = 0.8;
    col[i * 3 + 1] = 0.85;
    col[i * 3 + 2] = 1;
  }

  addPoints(group, pos, col, { size: 0.85, opacity: 0.85, additive: true });
}

/** Interstellar dust: dark, non-additive points that occlude the arms. */
function addDust(group) {
  const dustN = 7000;
  const dpos = new Float32Array(dustN * 3);
  const dcol = new Float32Array(dustN * 3);
  for (let d = 0; d < dustN; d++) {
    const theta = rng(88 + d)() * 6.2;
    const radius = 24 + rng(200 + d)() * 110;
    const angle = theta + 0.18;
    const spread = (rng(400 + d)() - 0.5) * 5;
    dpos[d * 3] = Math.cos(angle) * radius + spread;
    dpos[d * 3 + 1] = (rng(600 + d)() - 0.5) * 1.2;
    dpos[d * 3 + 2] = Math.sin(angle) * radius + spread;
    dcol[d * 3] = 0.05;
    dcol[d * 3 + 1] = 0.03;
    dcol[d * 3 + 2] = 0.02;
  }
  addPoints(group, dpos, dcol, { size: 1.6, opacity: 0.2, additive: false });
}

function makeDiskGlow() {
  const canvas = document.createElement('canvas');
  canvas.width = 512;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(256, 256, 12, 256, 256, 250);
  g.addColorStop(0, 'rgba(255, 220, 160, 0.45)');
  g.addColorStop(0.15, 'rgba(255, 190, 120, 0.18)');
  g.addColorStop(0.45, 'rgba(140, 160, 255, 0.05)');
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 512);
  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
  return new THREE.Mesh(new THREE.PlaneGeometry(300, 300), mat);
}

/** Assemble the galaxy group and the Sun marker inside it. */
export function makeMilkyWay() {
  const group = new THREE.Group();

  addStarField(group, rng(260413));
  addDust(group);

  // Мягкое свечение плоскости диска
  const glow = makeDiskGlow();
  glow.rotation.x = -Math.PI / 2;
  group.add(glow);

  // Метка Солнца
  const sun = new THREE.Mesh(
    new THREE.SphereGeometry(1.0, 16, 12),
    new THREE.MeshBasicMaterial({ color: 0x9ad0ff })
  );
  sun.position.set(SUN_GALACTIC.x, SUN_GALACTIC.y, SUN_GALACTIC.z);
  group.add(sun);

  return { group, sunPosition: sun.position.clone() };
}
