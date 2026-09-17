import * as THREE from 'three';

export function makeLabel(text) {
  const canvas = document.createElement('canvas');
  canvas.width = 384;
  canvas.height = 96;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = 'rgba(6, 10, 22, 0.75)';
  if (typeof ctx.roundRect === 'function') {
    ctx.roundRect(10, 16, 364, 64, 16);
  } else {
    ctx.rect(10, 16, 364, 64);
  }
  ctx.fill();
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = '#eef3ff';
  ctx.font = '600 28px system-ui, -apple-system, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, 192, 48);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true }));
  sprite.scale.set(3.0, 0.75, 1);
  return sprite;
}