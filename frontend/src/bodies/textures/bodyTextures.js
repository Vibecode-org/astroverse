import * as THREE from 'three';
import { rgba } from '../utils/colorUtils.js';

const CDN_MAP = {
  sun: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/sunmap.jpg',
  mercury: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/mercurymap.jpg',
  venus: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/venusmap.jpg',
  earth: 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@dev/examples/textures/planets/earth_atmos_2048.jpg',
  moon: 'https://cdn.jsdelivr.net/gh/mrdoob/three.js@dev/examples/textures/planets/moon_1024.jpg',
  mars: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/marsmap1k.jpg',
  jupiter: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/jupitermap.jpg',
  saturn: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/saturnmap.jpg',
  uranus: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/uranusmap.jpg',
  neptune: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/neptunemap.jpg',
  pluto: 'https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/plutomap1k.jpg',
  io: 'https://cdn.jsdelivr.net/npm/artastra@1.0.8/textures/io.jpg',
  europa: 'https://cdn.jsdelivr.net/npm/artastra@1.0.8/textures/europa.jpg',
  ganymede: 'https://cdn.jsdelivr.net/npm/artastra@1.0.8/textures/ganymede.jpg',
  callisto: 'https://cdn.jsdelivr.net/npm/artastra@1.0.8/textures/callisto.jpg',
};

const loader = new THREE.TextureLoader();
loader.setCrossOrigin('anonymous');
const cache = new Map();

function canvasTexture(size, paint) {
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  paint(ctx, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.wrapS = THREE.RepeatWrapping;
  tex.wrapT = THREE.ClampToEdgeWrapping;
  return tex;
}

// Градиент рисуется с зеркальным повтором у левого/правого края, иначе элемент,
// попавший на шов сферы, обрезается и seam становится видимым.
function wrappedRadial(ctx, s, x, y, r, stops) {
  const paint = (cx) => {
    const g = ctx.createRadialGradient(cx, y, 0, cx, y, r);
    for (const [offset, color] of stops) g.addColorStop(offset, color);
    ctx.fillStyle = g;
    ctx.fillRect(cx - r, y - r, r * 2, r * 2);
  };
  paint(x);
  if (x - r < 0) paint(x + s);
  if (x + r > s) paint(x - s);
}

/** Фотосфера звезды.
 *
 * Сфера использует equirect-развёртку, поэтому крупный градиент в пространстве
 * текстуры превращается в жёсткий терминатор и вращается вместе с мешем. Текстура
 * поэтому несёт только поверхностную деталь — равномерную грануляцию и мягкие
 * пятна, — а потемнение к краю считается отдельно, в пространстве вида
 * (см. applyLimbDarkening в bodies/meshes/starPlanetMesh.js).
 */
function makePhotosphere(ctx, s, baseCol, grainCol, spotCol) {
  ctx.fillStyle = baseCol;
  ctx.fillRect(0, 0, s, s);

  // Кипящие конвективные ячейки: шум попиксельный, поэтому сам по себе бесшовный.
  const img = ctx.getImageData(0, 0, s, s);
  const d = img.data;
  for (let i = 0; i < s * s; i++) {
    const grain = (Math.random() - 0.5) * 24;
    const p = i * 4;
    d[p] = Math.max(0, Math.min(255, d[p] + grain));
    d[p + 1] = Math.max(0, Math.min(255, d[p + 1] + grain * 0.85));
    d[p + 2] = Math.max(0, Math.min(255, d[p + 2] + grain * 0.6));
  }
  ctx.putImageData(img, 0, 0);

  // Светлые гранулы — мягкие пятна, без резких краёв.
  for (let i = 0; i < 110; i++) {
    const x = Math.random() * s;
    const y = Math.random() * s;
    const r = 3 + Math.random() * 9;
    wrappedRadial(ctx, s, x, y, r, [
      [0, rgba(grainCol, 0.30)],
      [1, rgba(grainCol, 0)],
    ]);
  }

  // Звёздные пятна — тоже мягкие и низкоконтрастные.
  if (spotCol) {
    for (let i = 0; i < 5; i++) {
      const x = Math.random() * s;
      const y = s * (0.2 + Math.random() * 0.6);
      const r = 6 + Math.random() * 14;
      wrappedRadial(ctx, s, x, y, r, [
        [0, rgba(spotCol, 0.34)],
        [0.55, rgba(spotCol, 0.16)],
        [1, rgba(spotCol, 0)],
      ]);
    }
  }
}

const painters = {
  // O/B Голубые сверхгиганты (Ригель, Спика)
  star_blue: (ctx, s) => makePhotosphere(ctx, s, '#bcd8ff', '#eaf4ff', '#1e46a0'),
  // A Белые звезды (Сириус, Вега)
  star_white: (ctx, s) => makePhotosphere(ctx, s, '#ffffff', '#ffffff', null),
  // F/G Желтые звезды (Солнце, Альфа Центавра)
  star_yellow: (ctx, s) => makePhotosphere(ctx, s, '#ffe08a', '#fff3c4', '#96460a'),
  // K Оранжевые гиганты (Арктур, Альдебаран)
  star_orange: (ctx, s) => makePhotosphere(ctx, s, '#ffb45e', '#ffd8a0', '#782800'),
  // M Красные сверхгиганты (Бетельгейзе, Антарес)
  star_red: (ctx, s) => makePhotosphere(ctx, s, '#ff7a4a', '#ffab7a', '#5a0f00'),

  exoplanet_habitable: (ctx, s) => {
    ctx.fillStyle = '#0e3870';
    ctx.fillRect(0, 0, s, s);
    ctx.fillStyle = '#2d7a3a';
    for (let i = 0; i < 24; i++) {
      ctx.beginPath();
      ctx.arc(Math.random() * s, Math.random() * s, 10 + Math.random() * 40, 0, Math.PI * 2);
      ctx.fill();
    }
  },
  exoplanet_lava: (ctx, s) => {
    ctx.fillStyle = '#1c0c06';
    ctx.fillRect(0, 0, s, s);
    ctx.strokeStyle = '#ff4400';
    ctx.lineWidth = 2;
    for (let i = 0; i < 30; i++) {
      ctx.beginPath();
      ctx.moveTo(Math.random() * s, Math.random() * s);
      ctx.lineTo(Math.random() * s, Math.random() * s);
      ctx.stroke();
    }
  },
  rocky: (ctx, s) => {
    const img = ctx.createImageData(s, s);
    for (let i = 0; i < s * s; i++) {
      const v = 95 + Math.floor(Math.random() * 55);
      img.data[i * 4] = v;
      img.data[i * 4 + 1] = v;
      img.data[i * 4 + 2] = v + 4;
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  },
  // Лёд комет и ледяных карликовых. Раньше painter'а не было, поэтому все 80
  // комет молча попадали в rocky и были неотличимы от астероидов.
  ice: (ctx, s) => {
    const img = ctx.createImageData(s, s);
    for (let i = 0; i < s * s; i++) {
      const grain = Math.random();
      // Тёмные включения пыли на светлой ледяной поверхности.
      const dust = grain < 0.22 ? 0.45 : 1;
      const v = Math.floor((170 + grain * 70) * dust);
      img.data[i * 4] = v * 0.82;
      img.data[i * 4 + 1] = v * 0.93;
      img.data[i * 4 + 2] = v;
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  },
};

export function getTexture(name) {
  if (cache.has(name)) return cache.get(name);

  const url = CDN_MAP[name];
  if (url) {
    const tex = loader.load(
      url,
      (t) => { t.colorSpace = THREE.SRGBColorSpace; t.needsUpdate = true; },
      undefined,
      () => {}
    );
    tex.colorSpace = THREE.SRGBColorSpace;
    cache.set(name, tex);
    return tex;
  }

  const painter = painters[name] || painters.rocky;
  const fallback = canvasTexture(256, painter);
  cache.set(name, fallback);
  return fallback;
}

export function makeRingTexture() {
  if (cache.has('saturn_ring')) return cache.get('saturn_ring');
  const tex = loader.load('https://cdn.jsdelivr.net/gh/jeromeetienne/threex.planets@master/images/saturnringcolor.jpg', (t) => {
    t.colorSpace = THREE.SRGBColorSpace;
    t.needsUpdate = true;
  });
  tex.colorSpace = THREE.SRGBColorSpace;
  cache.set('saturn_ring', tex);
  return tex;
}