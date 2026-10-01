import * as THREE from 'three';
import {
  createBodyMesh, makeOrbit, makeAsteroidBelt, makeKuiperBelt, makeLabel,
  buildSolarLayout, buildBeltRanges, getBodyRadius, objectScale,
} from '../bodies/index.js';

/** Build the solar system: belts, planets, moons, orbit lines and labels.
 *
 * Bodies are added to the caller-owned `system` group and registered in the
 * shared `meshes` map by id. Returns the per-frame state the animation loop
 * needs: which objects orbit, which moons follow which parent, and which
 * labels to project each frame.
 */
export function buildSolarSystem(scaledObjects, system, scene) {
  const meshes = new Map();
  const orbitLines = [];
  const labels = [];
  const moons = [];

  // Раскладка считается один раз для всей системы: расстояния, реальные
  // размеры и ограниченные зазорами орбиты спутников.
  const solarLayout = buildSolarLayout(scaledObjects);

  // Пояса берут границы из реальных расстояний каталога: раньше радиусы
  // были захардкожены (24.5–33 и 168–238) и разошлись с астероидами после
  // смены шкалы — в сцене появились две расходящиеся полосы, которые и
  // читались как «ряд из комет».
  const belts = buildBeltRanges();
  const belt = makeAsteroidBelt(belts.belt);
  const kuiper = makeKuiperBelt(belts.kuiper);
  system.add(belt, kuiper);

  const solar = scaledObjects.filter((o) => o.scale === 'solar');
  const planets = {};

  solar.filter((o) => o.kind !== 'moon').forEach((obj) => {
    const mesh = createBodyMesh(obj);
    const place = solarLayout.get(obj.id) || {};
    const dist = place.distance ?? 0;
    mesh.userData.calculatedDistance = dist;
    mesh.userData.initialAngle = [...obj.id].reduce((angle, char) => angle + char.charCodeAt(0), 0) % 360 * Math.PI / 180;
    mesh.userData.currentAngle = mesh.userData.initialAngle;

    if (dist > 0) mesh.position.set(dist, 0, 0);
    system.add(mesh);
    meshes.set(obj.id, mesh);
    planets[obj.id] = mesh;

    // Орбиты рисуем только у планет и карликовых. 400 астероидов давали
    // 400 эллипсов-шумов, которые читались как «рядом стоящие линии».
    if (['planet', 'dwarf_planet'].includes(obj.kind) && dist > 0) {
      const orbit = makeOrbit(dist);
      system.add(orbit);
      orbitLines.push(orbit);
    }

    // Метка заводится только там, где её действительно показывают.
    // Раньше текстура 384x96 создавалась для каждого solar-объекта кроме
    // звёзд, а animate() показывал лишь планеты и карликовые: 494 метки
    // (~72 МБ видеопамяти) ради 14 видимых.
    if (['planet', 'dwarf_planet'].includes(obj.kind)) {
      const label = makeLabel(obj.name);
      label.visible = false;
      scene.add(label);
      labels.push({ label, mesh, type: obj.kind, id: obj.id });
    }
  });

  solar.filter((o) => o.kind === 'moon').forEach((obj) => {
    const parent = planets[obj.parent];
    const mesh = createBodyMesh(obj);
    const place = solarLayout.get(obj.id) || {};
    const moonDist = place.moonOrbit || (parent ? parent.userData.displayRadius * 2.5 : 1);

    const pivot = new THREE.Group();
    pivot.position.copy(parent ? parent.position : new THREE.Vector3());
    pivot.userData.initialAngle = place.moonPhase ?? 0;
    pivot.userData.inclination = place.moonInclination ?? 0;

    mesh.position.set(moonDist, 0, 0);
    pivot.add(mesh);

    const moonOrbit = makeOrbit(moonDist, 0x334466, 0.25);
    pivot.add(moonOrbit);

    system.add(pivot);
    meshes.set(obj.id, mesh);
    moons.push({ pivot, mesh, obj, parentId: obj.parent });
  });

  return { meshes, orbitLines, labels, moons, planets, solar, belt, kuiper };
}

/** Attach `displayRadius` and a resolved `scale` to every catalog object. */
export function scaleCatalog(objects) {
  return objects.map((obj) => ({
    ...obj,
    scale: objectScale(obj),
    displayRadius: getBodyRadius(obj),
  }));
}
