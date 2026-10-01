import * as THREE from 'three';
import { getTexture, makeRingTexture } from '../textures/bodyTextures.js';
import { makeStarCorona } from '../textures/starTextures.js';
import { sharedGeometry, sharedMaterial } from '../resources.js';

const SHELL_SEGMENTS = 40;
const SHELL_RINGS = 28;
const ATMOSPHERE_SEGMENTS = 36;
const ATMOSPHERE_RINGS = 24;
const RING_SEGMENTS = 96;
const GAS_GIANTS = ['jupiter', 'saturn', 'uranus', 'neptune'];

/** The catalog reuses a few dozen distinct radii, so shells are cached by radius
 * instead of allocating ~140 KB of vertices for every one of 3.2k bodies. */
function shellGeometry(radius) {
  return sharedGeometry(`shell:${radius}`, () =>
    new THREE.SphereGeometry(radius, SHELL_SEGMENTS, SHELL_RINGS));
}

/** У звёзд нет источника света: MeshBasicMaterial не считает освещение, и сфера
 * выглядит плоским диском. Потемнение к краю нельзя запечь в текстуру — на
 * equirect-сфере оно превращается в терминатор и вращается вместе с мешем.
 * Поэтому фактор N·V считается на пиксель и применяется к diffuseColor.
 *
 * Нормаль берётся из чанков самого three, но кладётся в СВОЕ varying: в
 * MeshBasicMaterial `vNormal` объявлен во фрагментном шейдере всегда, а в
 * вершинном — только под USE_ENVMAP || USE_SKINNING. Если просто прочитать
 * готовый `vNormal`, линковщик ругается «FRAGMENT varying vNormal does not match
 * any VERTEX varying» и программа не линкуется.
 *
 * `vViewPosition` в MeshBasicMaterial тоже не объявлен, поэтому направление на
 * камеру добавляется своим varying из mvPosition.
 */
const LIMB_VERTEX_PRELUDE = 'varying vec3 vAstroNormal;\nvarying vec3 vAstroView;\n';
const LIMB_FRAGMENT_PRELUDE = 'varying vec3 vAstroNormal;\nvarying vec3 vAstroView;\n';

function applyLimbDarkening(material) {
  material.onBeforeCompile = (shader) => {
    shader.vertexShader = shader.vertexShader
      .replace('void main() {', LIMB_VERTEX_PRELUDE + 'void main() {')
      .replace('#include <begin_vertex>', [
        '#include <beginnormal_vertex>',
        '#include <defaultnormal_vertex>',
        'vAstroNormal = normalize( transformedNormal );',
        '#include <begin_vertex>',
      ].join('\n'))
      .replace('#include <project_vertex>', '#include <project_vertex>\n\tvAstroView = -mvPosition.xyz;');
    shader.fragmentShader = shader.fragmentShader
      .replace('void main() {', LIMB_FRAGMENT_PRELUDE + 'void main() {')
      .replace('#include <opaque_fragment>', [
        'float ndv = clamp(dot(normalize(vAstroNormal), normalize(vAstroView)), 0.0, 1.0);',
        // Умножать надо outgoingLight, а не diffuseColor: в MeshBasicMaterial
        // diffuseColor уже входит в reflectedLight.indirectDiffuse ВЫШЕ, и к
        // #include <opaque_fragment> от него ничего не осталось.
        'outgoingLight *= mix(0.55, 1.0, pow(ndv, 0.8));',
        '#include <opaque_fragment>',
      ].join('\n'));
  };
  // Все звёздные материалы получают одинаковую правку шейдера и должны попасть
  // в один скомпилированный программный кэш, но не смешиваться с обычными.
  material.customProgramCacheKey = () => 'astroverse-star-limb';
}

function shellMaterial(isStar, texName, smooth) {
  const map = getTexture(texName);
  return sharedMaterial(`shell:${isStar}:${texName}:${smooth}`, () => {
    const material = isStar
      ? new THREE.MeshBasicMaterial({ color: 0xffffff, map })
      : new THREE.MeshStandardMaterial({
        color: 0xffffff,
        map,
        roughness: smooth ? 0.5 : 0.8,
        metalness: 0.05,
      });
    if (isStar) applyLimbDarkening(material);
    return material;
  });
}

function atmosphereMesh(radius) {
  const geometry = sharedGeometry(`atmosphere:${radius}`, () =>
    new THREE.SphereGeometry(radius * 1.015, ATMOSPHERE_SEGMENTS, ATMOSPHERE_RINGS));
  const material = sharedMaterial('atmosphere', () => new THREE.MeshStandardMaterial({
    color: 0x4aa3ff,
    transparent: true,
    opacity: 0.2,
    roughness: 1.0,
  }));
  return new THREE.Mesh(geometry, material);
}

function ringMesh(radius, rings) {
  const inner = radius * rings.inner;
  const outer = radius * rings.outer;
  const geometry = sharedGeometry(`ring:${inner}:${outer}`, () =>
    new THREE.RingGeometry(inner, outer, RING_SEGMENTS, 4));
  const material = sharedMaterial('ring', () => new THREE.MeshStandardMaterial({
    map: makeRingTexture(),
    side: THREE.DoubleSide,
    transparent: true,
    opacity: 0.9,
    roughness: 0.6,
  }));
  const ring = new THREE.Mesh(geometry, material);
  ring.rotation.x = Math.PI / 2;
  return ring;
}

export function createStarPlanetMesh(obj) {
  // displayRadius — реальный размер в радиусах Земли, посчитанный в
  // solarLayout.js из физического radius_km. obj.radius — авторское поле
  // оформления и может быть произвольным. Наклон берётся только у числа:
  // объект в tilt даёт NaN в rotation, и NaN расходится дальше — в
  // controls.target и camera.position, — уже без всякой ошибки в консоли.
  const radius = obj.id === 'phobos' ? 0.38 : obj.id === 'deimos' ? 0.026 : (obj.displayRadius ?? obj.radius ?? 0.4);
  const isStar = obj.kind === 'star';
  const tilt = typeof obj.tilt === 'number' && Number.isFinite(obj.tilt) ? obj.tilt : 0;

  // Определяем текстуру
  let texName = obj.texture;
  if (isStar) {
    const t = obj.temperature_k || 5500;
    texName = t > 8500 ? 'star_blue' : t > 7000 ? 'star_white' : t > 5200 ? 'star_yellow' : t > 3700 ? 'star_orange' : 'star_red';
  } else if (!texName) {
    if (obj.kind === 'exoplanet') {
      const t = obj.temperature_k || 300;
      texName = t > 500 ? 'exoplanet_lava' : 'exoplanet_habitable';
    } else {
      texName = 'rocky';
    }
  }

  const mesh = new THREE.Mesh(shellGeometry(radius), shellMaterial(isStar, texName, GAS_GIANTS.includes(obj.texture)));
  mesh.userData = obj;
  if (tilt) mesh.rotation.z = (tilt * Math.PI) / 180;

  if (isStar) {
    // Короче, чем было (3.6): при радиусе Солнца 7 спрайт короны иначе
    // накрывал собой Меркурий и Венеру.
    mesh.add(makeStarCorona(obj.color || '#ffb74d', radius * 2.2));
  }

  if (obj.id === 'earth') {
    mesh.add(atmosphereMesh(radius));
  }

  if (obj.rings) {
    mesh.add(ringMesh(radius, obj.rings));
  }

  return mesh;
}
