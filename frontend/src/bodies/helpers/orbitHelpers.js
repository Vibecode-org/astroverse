import * as THREE from 'three';
import { starPointTexture } from '../textures/starTextures.js';
import { hashUnit } from '../utils/hash.js';

/** Ортонормированный базис плоскости орбиты, детерминированный по id системы.
 *
 * Плоскость общая для всех тел системы — так и должно быть, — а фаза у каждого
 * тела своя (см. orbitPhase), иначе планеты одной системы совпали бы в точке. */
export function orbitFrame(systemId) {
  const inclination = hashUnit(systemId + ':inc') * Math.PI * 0.55;
  const node = hashUnit(systemId + ':node') * Math.PI * 2;
  const cosI = Math.cos(inclination);
  const sinI = Math.sin(inclination);
  return {
    // X смотрит на восходящий узел, Y — на 90° вперёд в плоскости орбиты.
    x: new THREE.Vector3(Math.cos(node), 0, Math.sin(node)),
    y: new THREE.Vector3(-Math.sin(node) * cosI, sinI, Math.cos(node) * cosI),
  };
}

/** Начальная фаза тела на орбите, своя для каждого тела. */
export function orbitPhase(bodyId) {
  return hashUnit(bodyId + ':phase') * Math.PI * 2;
}

/** Визуальный радиус орбиты вокруг звезды.
 *
 * Реальные полуоси (0.02–10 а.е.) нечитаемы рядом с радиусом звезды: при
 * масштабировании «как есть» планета снова окажется внутри хозяина. Поэтому
 * орбита растягивается в диапазоне «несколько радиусов звезды», но порядок по
 * полуоси сохраняется. Нижняя граница подобрана так, чтобы камера при
 * приближении к планете (дистанция ≈ 2.8·radius) не заезжала внутрь звезды. */
export function getLocalOrbitRadius(obj, parentRadius = 0.35) {
  const base = parentRadius * 3.6;
  const au = obj.au;
  if (typeof au !== 'number' || !Number.isFinite(au) || au <= 0) return base;
  return base * (0.85 + 0.3 * Math.min(au, 8));
}

/** Положение тела на круговой орбите. Пишет в `target`, не создавая объектов:
 * эта функция зовётся каждый кадр для каждого локального тела. */
export function placeOnOrbit(target, center, frame, radius, angle) {
  const cos = Math.cos(angle) * radius;
  const sin = Math.sin(angle) * radius;
  return target
    .set(frame.x.x * cos + frame.y.x * sin,
      frame.x.y * cos + frame.y.y * sin,
      frame.x.z * cos + frame.y.z * sin)
    .add(center);
}

export function makeOrbit(r, color = 0x242d42, opacity = 0.4) {
  const curve = new THREE.EllipseCurve(0, 0, r, r * 0.995, 0, Math.PI * 2, false, 0);
  const points = curve.getPoints(256).map((p) => new THREE.Vector3(p.x, 0, p.y));
  return new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity }),
  );
}

export function makeAsteroidBelt(span = [45, 58]) {
  const group = new THREE.Group();
  const n = 1800;
  const [inner, outer] = span;
  const width = Math.max(outer - inner, inner * 0.15);
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const r = inner + Math.random() * width;
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = (Math.random() - 0.5) * width * 0.06;
    pos[i * 3 + 2] = Math.sin(a) * r;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  group.add(new THREE.Points(geo, new THREE.PointsMaterial({
    color: 0x8b8174,
    size: 0.09,
    map: starPointTexture,
    transparent: true,
    sizeAttenuation: true
  })));
  return group;
}

export function makeKuiperBelt(span = [280, 380]) {
  const group = new THREE.Group();
  const n = 2400;
  const [inner, outer] = span;
  const width = Math.max(outer - inner, inner * 0.2);
  const pos = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2;
    const r = inner + Math.random() * width;
    pos[i * 3] = Math.cos(a) * r;
    pos[i * 3 + 1] = (Math.random() - 0.5) * width * 0.05;
    pos[i * 3 + 2] = Math.sin(a) * r;
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  group.add(new THREE.Points(geo, new THREE.PointsMaterial({
    color: 0x6a7a99,
    size: 0.08,
    map: starPointTexture,
    transparent: true,
    opacity: 0.6
  })));
  return group;
}