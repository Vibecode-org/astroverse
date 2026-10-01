import * as THREE from 'three';
import { sharedMaterial, sharedTexture } from '../resources.js';
import { rgba } from '../utils/colorUtils.js';

const starPointTexture = (() => {
  const canvas = document.createElement('canvas');
  canvas.width = 64;
  canvas.height = 64;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  g.addColorStop(0, 'rgba(255, 255, 255, 1)');
  g.addColorStop(0.25, 'rgba(255, 240, 200, 0.8)');
  g.addColorStop(0.6, 'rgba(255, 200, 150, 0.2)');
  g.addColorStop(1, 'rgba(0, 0, 0, 0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(canvas);
})();

function buildCoronaTexture(colorHex) {
  const canvas = document.createElement('canvas');
  canvas.width = 256;
  canvas.height = 256;
  const ctx = canvas.getContext('2d');
  const cx = 128;
  const cy = 128;

  // Дифракционные лучи
  const ray = ctx.createLinearGradient(0, cy, 256, cy);
  ray.addColorStop(0, 'rgba(255,255,255,0)');
  ray.addColorStop(0.5, 'rgba(255,255,255,0.30)');
  ray.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = ray;
  ctx.fillRect(0, cy - 1, 256, 2);

  const rayV = ctx.createLinearGradient(cx, 0, cx, 256);
  rayV.addColorStop(0, 'rgba(255,255,255,0)');
  rayV.addColorStop(0.5, 'rgba(255,255,255,0.30)');
  rayV.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = rayV;
  ctx.fillRect(cx - 1, 0, 2, 256);

  // Ореол. Прозрачный в центре: спрайт аддитивный, и непрозрачное ядро
  // перекрывало бы саму фотосферу, выбивая её в белое пятно.
  // Лимб сферы попадает примерно в 1/3 радиуса спрайта, поэтому ореол
  // начинается сразу за ним.
  const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, 126);
  g.addColorStop(0, rgba(colorHex, 0));
  g.addColorStop(0.22, rgba(colorHex, 0));
  g.addColorStop(0.36, rgba(colorHex, 0.55));
  g.addColorStop(0.58, rgba(colorHex, 0.20));
  g.addColorStop(1, rgba(colorHex, 0));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 256, 256);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function makeStarCorona(colorHex, scale = 4.5) {
  // The catalog has ~1.2k stars but only a handful of colors; one texture and
  // one material per color keeps this at a few MB instead of a few hundred.
  // safeColor inside rgba keeps a malformed color from throwing in addColorStop
  // and taking the entire scene down with it.
  const map = sharedTexture(`corona:${colorHex}`, () => buildCoronaTexture(colorHex));
  const material = sharedMaterial(`corona:${colorHex}`, () => new THREE.SpriteMaterial({
    map,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  }));
  const sprite = new THREE.Sprite(material);
  sprite.scale.setScalar(scale);
  return sprite;
}

export { starPointTexture };