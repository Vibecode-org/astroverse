import * as THREE from 'three';


export function makeNebulaCloudSprite(colorHex, scale = 5.0) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  const ctx = canvas.getContext('2d');
  const baseCol = new THREE.Color(colorHex);
  const r = Math.round(baseCol.r * 255);
  const g = Math.round(baseCol.g * 255);
  const b = Math.round(baseCol.b * 255);

  const grad = ctx.createRadialGradient(128, 128, 10, 128, 128, 120);
  grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.55)`);
  grad.addColorStop(0.35, `rgba(${r}, ${g}, ${b}, 0.35)`);
  grad.addColorStop(0.7, `rgba(${Math.round(r * 0.8)}, ${Math.round(g * 0.7)}, ${b}, 0.12)`);
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, 256, 256);

  const tex = new THREE.CanvasTexture(canvas);
  const mat = new THREE.SpriteMaterial({
    map: tex,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const sprite = new THREE.Sprite(mat);
  sprite.scale.setScalar(scale);
  return sprite;
}

export function makeSpiralGalaxyTexture(colorHex = '#99ccff') {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const cx = size / 2;
  const cy = size / 2;

  const bulge = ctx.createRadialGradient(cx, cy, 0, cx, cy, size * 0.22);
  bulge.addColorStop(0, 'rgba(255, 250, 230, 1.0)');
  bulge.addColorStop(0.25, 'rgba(255, 220, 160, 0.75)');
  bulge.addColorStop(0.6, 'rgba(255, 180, 120, 0.25)');
  bulge.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = bulge;
  ctx.fillRect(0, 0, size, size);

  const baseCol = new THREE.Color(colorHex);
  const armCol = `${Math.round(baseCol.r * 255)}, ${Math.round(baseCol.g * 255)}, ${Math.round(baseCol.b * 255)}`;

  for (let arm = 0; arm < 2; arm++) {
    const offset = arm * Math.PI;
    for (let t = 0; t < 220; t++) {
      const theta = offset + (t / 220) * Math.PI * 2.7;
      const r = 20 + Math.pow(t / 220, 1.35) * (size * 0.42);
      const x = cx + Math.cos(theta) * r + (Math.random() - 0.5) * 14;
      const y = cy + Math.sin(theta) * r + (Math.random() - 0.5) * 14;
      const alpha = (1 - (t / 220) * 0.65) * 0.35;

      ctx.fillStyle = `rgba(${armCol}, ${alpha})`;
      ctx.beginPath();
      ctx.arc(x, y, 5 + Math.random() * 10, 0, Math.PI * 2);
      ctx.fill();

      if (Math.random() < 0.2) {
        ctx.fillStyle = `rgba(180, 220, 255, ${alpha * 1.6})`;
        ctx.beginPath();
        ctx.arc(x, y, 2 + Math.random() * 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }

  const halo = ctx.createRadialGradient(cx, cy, size * 0.15, cx, cy, size * 0.48);
  halo.addColorStop(0, `rgba(${armCol}, 0.18)`);
  halo.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = halo;
  ctx.fillRect(0, 0, size, size);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makeAccretionDiskTexture(innerRatio = 0.32) {
  const size = 512;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const cx = size / 2;
  const cy = size / 2;
  const rIn = cx * innerRatio;
  const rOut = cx * 0.98;

  const g = ctx.createRadialGradient(cx, cy, rIn * 0.85, cx, cy, rOut);
  g.addColorStop(0, 'rgba(0,0,0,0)');
  g.addColorStop(innerRatio * 0.92, 'rgba(0,0,0,0)');
  g.addColorStop(innerRatio, 'rgba(255, 255, 255, 1)'); // Ослепительная граница ISCO
  g.addColorStop(innerRatio + 0.08, 'rgba(255, 240, 190, 0.95)');
  g.addColorStop(innerRatio + 0.22, 'rgba(255, 160, 45, 0.85)');
  g.addColorStop(innerRatio + 0.45, 'rgba(215, 65, 15, 0.55)');
  g.addColorStop(0.88, 'rgba(130, 20, 5, 0.2)');
  g.addColorStop(1.0, 'rgba(0,0,0,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);

  // Релятивистское усиление Доплера (левая сторона слепит яркостью, правая — в тени)
  const beam = ctx.createLinearGradient(0, cy, size, cy);
  beam.addColorStop(0.0, 'rgba(255, 255, 255, 0.45)');
  beam.addColorStop(0.4, 'rgba(255, 255, 255, 0.1)');
  beam.addColorStop(1.0, 'rgba(0, 0, 0, 0.55)');
  ctx.fillStyle = beam;
  ctx.globalCompositeOperation = 'overlay';
  ctx.fillRect(0, 0, size, size);

  ctx.globalCompositeOperation = 'lighter';
  for (let i = 0; i < 24; i++) {
    const angle = (i / 24) * Math.PI * 2;
    ctx.beginPath();
    for (let r = rIn; r < rOut; r += 4) {
      const theta = angle + Math.log(r / rIn) * 3.5;
      const x = cx + Math.cos(theta) * r;
      const y = cy + Math.sin(theta) * r;
      if (r === rIn) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = `rgba(255, ${150 + (i % 5) * 20}, 50, 0.12)`;
    ctx.lineWidth = 3;
    ctx.stroke();
  }

  ctx.globalCompositeOperation = 'source-over';

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

function makePhotonRingTexture() {
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  const cx = size / 2;
  const cy = size / 2;

  const g = ctx.createRadialGradient(cx, cy, cx * 0.72, cx, cy, cx * 0.98);
  g.addColorStop(0, 'rgba(255, 255, 255, 0)');
  g.addColorStop(0.5, 'rgba(255, 250, 230, 0.95)');
  g.addColorStop(1, 'rgba(255, 180, 80, 0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export { makeAccretionDiskTexture, makePhotonRingTexture };