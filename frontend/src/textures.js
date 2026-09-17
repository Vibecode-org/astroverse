import * as THREE from 'three';

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

// НАСТОЯЩИЕ ЗВЁЗДНЫЕ ФОТОСФЕРЫ: ПОТЕМНЕНИЕ К КРАЮ (LIMB DARKENING) + КИПЯЩАЯ ПЛАЗМА
function makePhotosphere(ctx, s, centerCol, edgeCol, spotCol) {
  const cx = s / 2;
  const cy = s / 2;

  // 1. Физическое потемнение к краю (Limb Darkening)
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, cx);
  g.addColorStop(0, centerCol);
  g.addColorStop(0.65, centerCol);
  g.addColorStop(0.9, edgeCol);
  g.addColorStop(1.0, '#110500');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);

  // 2. Кипящие конвективные ячейки (грануляция)
  const img = ctx.getImageData(0, 0, s, s);
  for (let i = 0; i < s * s; i++) {
    const noise = (Math.random() - 0.5) * 22;
    img.data[i * 4] = Math.max(0, Math.min(255, img.data[i * 4] + noise));
    img.data[i * 4 + 1] = Math.max(0, Math.min(255, img.data[i * 4 + 1] + noise * 0.8));
    img.data[i * 4 + 2] = Math.max(0, Math.min(255, img.data[i * 4 + 2] + noise * 0.5));
  }
  ctx.putImageData(img, 0, 0);

  // 3. Звёздные пятна
  if (spotCol) {
    ctx.fillStyle = spotCol;
    for (let i = 0; i < 16; i++) {
      ctx.beginPath();
      ctx.arc(Math.random() * s, Math.random() * s, 2 + Math.random() * 8, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}

const painters = {
  // O/B Голубые сверхгиганты (Ригель, Спика)
  star_blue: (ctx, s) => makePhotosphere(ctx, s, '#ffffff', '#5599ff', 'rgba(0, 60, 180, 0.4)'),
  // A Белые звезды (Сириус, Вега)
  star_white: (ctx, s) => makePhotosphere(ctx, s, '#ffffff', '#c5dcff', null),
  // F/G Желтые звезды (Солнце, Альфа Центавра)
  star_yellow: (ctx, s) => makePhotosphere(ctx, s, '#ffffff', '#ff8800', '#772200'),
  // K Оранжевые гиганты (Арктур, Альдебаран)
  star_orange: (ctx, s) => makePhotosphere(ctx, s, '#ffe8aa', '#b83800', '#4a1100'),
  // M Красные сверхгиганты (Бетельгейзе, Антарес)
  star_red: (ctx, s) => makePhotosphere(ctx, s, '#ff7744', '#550800', '#220000'),

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