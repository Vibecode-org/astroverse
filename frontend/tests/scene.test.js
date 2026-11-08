import { expect, test, vi } from 'vitest';
import * as THREE from 'three';
import { createBodyMesh } from '../src/bodies/createBodyMesh.js';
import { disposeSceneResources, sharedGeometry, sharedMaterial, sharedTexture,
  registerSharedTexture } from '../src/bodies/resources.js';
import { createLOD } from '../src/scene/lodController.js';
import { createLODPoints } from '../src/scene/lodPoints.js';
import { createLODInstanced } from '../src/scene/lodInstanced.js';
import { applyViewState } from '../src/scene/viewState.js';
import { attachPicking } from '../src/scene/picking.js';
import { buildDeepSky } from '../src/scene/buildDeepSky.js';
import { buildSolarSystem, scaleCatalog } from '../src/scene/buildSolarSystem.js';
import { buildSolarLayout, getSolarDistance, getBodyRadius, buildBeltRanges } from '../src/bodies/solarLayout.js';
import { makeMilkyWay } from '../src/bodies/meshes/milkyWayMesh.js';
import { startAnimationLoop } from '../src/scene/animation.js';

const body = (id, kind = 'star', extra = {}) => ({ id, name: id, kind, scale: 'local', radius: 1, ...extra });
const cameraAt = (z = 100) => {
  const camera = new THREE.PerspectiveCamera(50, 1, .01, 1e6);
  camera.position.z = z; camera.lookAt(0, 0, 0); camera.updateMatrixWorld(); return camera;
};
const canvas = () => {
  const el = document.createElement('canvas');
  Object.defineProperty(el, 'clientHeight', { value: 1000 });
  el.getBoundingClientRect = () => ({ left: 10, top: 20, width: 1000, height: 1000 });
  return el;
};

test('scene disposal releases owned resources once and preserves every shared cache', () => {
  const sharedG = sharedGeometry('test', () => new THREE.SphereGeometry());
  expect(sharedGeometry('test', () => { throw Error('rebuilt'); })).toBe(sharedG);
  const sharedT = sharedTexture('test', () => new THREE.Texture());
  expect(sharedTexture('test', () => null)).toBe(sharedT);
  expect(registerSharedTexture(sharedT)).toBe(sharedT);
  const sharedM = sharedMaterial('test', () => new THREE.MeshBasicMaterial({ map: sharedT }));
  expect(sharedMaterial('test', () => null)).toBe(sharedM);
  const texture = new THREE.Texture(), material = new THREE.MeshBasicMaterial({ map: texture });
  const group = new THREE.Group(), owned = new THREE.Mesh(new THREE.BoxGeometry(), [material, material.clone()]);
  group.add(new THREE.Mesh(sharedG, sharedM), owned, new THREE.Object3D());
  const t = vi.spyOn(texture, 'dispose'), g = vi.spyOn(owned.geometry, 'dispose');
  const sm = vi.spyOn(sharedM, 'dispose'), sg = vi.spyOn(sharedG, 'dispose'), st = vi.spyOn(sharedT, 'dispose');
  disposeSceneResources(group);
  expect(t).toHaveBeenCalledTimes(1); expect(g).toHaveBeenCalledTimes(1);
  expect(sm).not.toHaveBeenCalled(); expect(sg).not.toHaveBeenCalled(); expect(st).not.toHaveBeenCalled();
});

test('L0 batches position uploads; L1 uses radius matrices and ignores unknown indices', () => {
  const objects = [body('a'), body('b', 'exoplanet', { displayRadius: .2 }),
    body('c', 'cluster', { radius: undefined }), body('d', 'planet')];
  const points = createLODPoints(objects), attr = points.object.geometry.attributes.position;
  const version = attr.version;
  points.commit(); expect(attr.version).toBe(version);
  points.setPosition(0, new THREE.Vector3(1, 2, 3)); points.commit();
  expect(attr.version).toBe(version + 1); expect([...attr.array.slice(0, 3)]).toEqual([1, 2, 3]);
  points.setViewport(123); expect(points.object.material.uniforms.uFocal.value).toBe(123);
  const instances = createLODInstanced(objects);
  instances.show(0, new THREE.Vector3(1, 2, 3), 2); instances.show(999, new THREE.Vector3(), 1);
  const matrix = new THREE.Matrix4(); instances.meshes[0].getMatrixAt(0, matrix);
  expect(new THREE.Vector3().setFromMatrixPosition(matrix).toArray()).toEqual([1, 2, 3]);
  expect(matrix.elements[0]).toBe(2);
  instances.hide(0); instances.hide(999); instances.commit(); instances.commit();
  instances.meshes[0].getMatrixAt(0, matrix); expect(matrix.elements[0]).toBe(0);
  instances.dispose(); points.dispose();
});

test('LOD budget, picking, selection pins, scale switches and disposal work together', () => {
  const objects = Array.from({ length: 35 }, (_, i) => body(String(i)));
  objects.push(body('cluster', 'cluster', { scale: 'galaxy' }), body('sun', 'star', { scale: 'solar' }));
  const group = new THREE.Group(), galaxyGroup = new THREE.Group(), meshes = new Map();
  galaxyGroup.visible = false;
  for (const obj of objects) {
    const m = new THREE.Object3D(); m.userData.displayRadius = 1;
    (obj.scale === 'galaxy' ? galaxyGroup : group).add(m); meshes.set(obj.id, m);
  }
  const camera = cameraAt(10), el = canvas();
  const lod = createLOD({ objects, meshes, camera, domElement: el, group, galaxyGroup });
  for (let i = 0; i < 26; i++) lod.update();
  expect(lod.counts().reduce((a, b) => a + b, 0)).toBe(35);
  expect(lod.counts()[2]).toBeLessThanOrEqual(20);
  expect(lod.pick(510, 520)?.id).toBeDefined();
  expect(lod.pick(-500, -500)).toBe(null);
  expect(lod.ensureL2({ id: 'absent' })).toBe(null);
  expect(lod.ensureL2(objects[34])).toBeTruthy();
  expect(lod.ensureL2(objects[34])).toBeTruthy();
  lod.ensureL2(objects[33]); lod.releaseL2();
  camera.position.z = 10000;
  for (let i = 0; i < 26; i++) lod.update();
  expect(lod.counts()[0]).toBe(35);
  group.visible = false; galaxyGroup.visible = true; lod.update();
  expect(lod.counts().reduce((a, b) => a + b, 0)).toBe(1);
  galaxyGroup.visible = false; lod.update(); expect(lod.pick(510, 520)).toBe(null);
  lod.dispose(); expect(group.children.filter(c => c.isPoints || c.isInstancedMesh)).toHaveLength(0);
});

test('empty LOD and no galaxy group do not allocate detailed bodies', () => {
  const lod = createLOD({ objects: [], meshes: new Map(), camera: cameraAt(), domElement: canvas(), group: new THREE.Group() });
  expect(lod.counts()).toEqual([0, 0, 0]); expect(lod.pick(0, 0)).toBe(null); lod.dispose();
});

test.each([
  body('star'), body('hot', 'star', { temperature_k: 15000 }),
  body('cool', 'star', { temperature_k: 3000 }), body('earth', 'planet', { tilt: 23.4 }),
  body('saturn', 'planet', { rings: { inner: 1.2, outer: 2 } }),
  ...[100, 500, 1500].map(t => body(`exo${t}`, 'exoplanet', { temperature_k: t })),
  body('black', 'black_hole'), body('jets', 'black_hole', { has_jet: true }),
  body('nebula', 'nebula'), body('m45', 'cluster'), body('cluster', 'cluster'),
  body('m104', 'galaxy'), body('galaxy', 'galaxy'),
])('body factory builds finite transforms for $id', obj => {
  const mesh = createBodyMesh(obj);
  expect(mesh.isObject3D).toBe(true);
  mesh.traverse(child => expect([...child.position, ...child.scale, child.rotation.x,
    child.rotation.y, child.rotation.z].every(Number.isFinite)).toBe(true));
  disposeSceneResources(mesh);
});

test('solar layout modes, moon containment and scaled-row cache preserve input data', () => {
  const objects = [body('sun', 'star', { scale: 'solar' }),
    body('earth', 'planet', { scale: 'solar', parent: 'sun', radius_km: 6371, au: 1 }),
    body('mars', 'planet', { scale: 'solar', parent: 'sun', radius_km: 3390, au: 1.5 }),
    ...[1, 2].map(i => body(`moon${i}`, 'moon', { scale: 'solar', parent: 'earth', moon_distance: i,
      moon_distance_km: i * 200000, radius_km: 1000 })),
    body('orphan', 'moon', { scale: 'solar', parent: 'missing' }), body('other')];
  const snapshot = structuredClone(objects);
  for (const mode of ['compact', 'real', 'unknown']) {
    const layout = buildSolarLayout(objects, mode);
    expect(layout.has('other')).toBe(false);
    expect(layout.get('moon1').moonOrbit).toBeGreaterThan(layout.get('earth').radius);
    const rows = scaleCatalog(objects, mode);
    expect(scaleCatalog(objects, mode)).toBe(rows);
    expect(rows[1]).not.toBe(objects[1]);
    const built = buildSolarSystem(rows, new THREE.Group(), new THREE.Scene(), mode);
    expect(built.meshes.has('earth')).toBe(true); expect(built.moons).toHaveLength(3);
    expect(buildBeltRanges(mode).belt[1]).toBeGreaterThan(buildBeltRanges(mode).belt[0]);
  }
  expect(objects).toEqual(snapshot);
  expect(getBodyRadius(objects[1])).toBe(1); expect(getBodyRadius(objects[0], 'real')).toBeGreaterThan(100);
  expect(getBodyRadius(body('a', 'asteroid', { radius: .001 }))).toBe(.4);
  expect(getSolarDistance({ au: NaN, distance: 12 })).toBe(12);
  expect(getSolarDistance({}, 'real')).toBeGreaterThan(20000);
});

test('deep-sky builder uses binary positions and places children around their root', () => {
  const objects = [body('host', 'star', { _binaryPosition: [10, 20, 30] }),
    body('planet', 'exoplanet', { parent: 'host', au: 1, period_days: 20 }),
    body('root'), body('c', 'cluster', { scale: 'galaxy' }),
    body('black', 'black_hole', { scale: 'galaxy' })];
  const meshes = new Map();
  const result = buildDeepSky(objects, new THREE.Group(), new THREE.Group(), meshes);
  expect(meshes.get('host').position.toArray()).toEqual([10, 20, 30]);
  expect(meshes.get('planet').position.distanceTo(meshes.get('host').position)).toBeGreaterThan(1);
  expect(result.localOrbits).toHaveLength(1); expect(result.blackHolesList).toHaveLength(1);
  expect(makeMilkyWay().group.children.length).toBeGreaterThan(0);
});

test('raycast selection respects hidden parents, drag threshold and listener cleanup', () => {
  const el = canvas(), camera = cameraAt(), group = new THREE.Group();
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(10), new THREE.MeshBasicMaterial());
  group.add(mesh); group.updateMatrixWorld();
  const obj = body('hit'), pick = vi.fn(), fallback = vi.fn(() => obj);
  const detach = attachPicking({ domElement: el, camera, meshes: new Map([['a', mesh]]),
    catalogByMesh: new Map([[group, obj]]), onPick: pick, lod: { pick: fallback } });
  const event = (type, x = 510, y = 520) => el.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y }));
  event('pointerdown'); event('pointerup'); expect(pick).toHaveBeenCalledWith(obj, 'local');
  pick.mockClear(); event('pointerdown'); event('pointermove', 530); event('pointerup'); expect(pick).not.toHaveBeenCalled();
  group.visible = false; event('pointerdown'); event('pointerup'); expect(fallback).toHaveBeenCalled();
  detach(); pick.mockClear(); event('pointerdown'); event('pointerup'); expect(pick).not.toHaveBeenCalled();
});

test('time-driven animation is reproducible, pause skips orbit work and follow tracks translation', () => {
  let callback;
  vi.stubGlobal('requestAnimationFrame', vi.fn(cb => { callback = cb; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  const mesh = new THREE.Object3D(); mesh.userData = { calculatedDistance: 10, initialAngle: .5 };
  const camera = cameraAt(), controls = { target: new THREE.Vector3(), update: vi.fn() };
  const renderer = { render: vi.fn(), info: { render: { calls: 1, triangles: 2, points: 0, lines: 0 } } };
  const state = { simTime: Date.UTC(2000, 0, 1, 12), view: 'solar' };
  const args = { state, camera, controls, renderer, scene: new THREE.Scene(),
    solar: [body('p', 'planet', { period_days: 365 })], meshes: new Map([['p', mesh]]),
    moons: [], localOrbits: [], blackHolesList: [], labels: [], lod: { update: vi.fn(), counts: () => [1, 0, 0] } };
  const stop = startAnimationLoop(args), initial = mesh.position.clone();
  callback(); expect(mesh.position.toArray()).toEqual(initial.toArray());
  state.simTime += 100 * 86400000; callback(); expect(mesh.position.distanceTo(initial)).toBeGreaterThan(1);
  state.simTime -= 100 * 86400000; callback(); expect(mesh.position.toArray()).toEqual(initial.toArray());
  state.followObject = { id: 'p' }; state.followCamera = true;
  callback(); const previous = camera.position.clone(); mesh.position.x += 2; callback();
  expect(camera.position.x - previous.x).toBe(2); expect(state.metrics.calls).toBe(1);
  stop(); expect(cancelAnimationFrame).toHaveBeenCalled();
});

test('view state isolates scales and tolerates an unmounted scene', () => {
  applyViewState({}, 'solar');
  const state = { scene: {}, system: {}, nearby: {}, galaxy: { group: {} }, galaxyMarkers: {}, sunLight: {}, ambient: {} };
  for (const view of ['solar', 'local', 'galaxy']) {
    applyViewState(state, view);
    expect([state.system.visible, state.nearby.visible, state.galaxy.group.visible].filter(Boolean)).toHaveLength(1);
    expect(state.sunLight.visible).toBe(view === 'solar');
  }
});
