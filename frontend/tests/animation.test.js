import { expect, test, vi } from 'vitest';
import * as THREE from 'three';
import { startAnimationLoop } from '../src/scene/animation.js';
import { orbitFrame } from '../src/bodies/helpers/orbitHelpers.js';

test('moons, optimized and fallback exoplanet orbits, lighting and labels all reverse deterministically', () => {
  let tick;
  vi.stubGlobal('requestAnimationFrame', vi.fn(cb => { tick = cb; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.spyOn(console, 'log').mockImplementation(() => {});
  window.__astroverseLodDebug = true;
  const host = new THREE.Object3D(), moon = new THREE.Object3D(), pivot = new THREE.Group();
  host.position.set(1, 2, 3); host.userData = { calculatedDistance: 2, initialAngle: .2 };
  host.userData.displayRadius = 2;
  pivot.userData = { initialAngle: .2, inclination: .3 };
  const fast = new THREE.Object3D(), fallback = new THREE.Object3D();
  const label = new THREE.Sprite(), disk = new THREE.Object3D(), lensHalo = new THREE.Object3D(), photonRing = new THREE.Object3D();
  const camera = new THREE.PerspectiveCamera(); camera.position.set(0, 1, 10);
  const renderer = { render: vi.fn(), info: { render: { calls: 1, triangles: 1, points: 1, lines: 1 } } };
  const state = { simTime: Date.UTC(2000, 0, 1, 12), view: 'solar',
    focusLight: new THREE.PointLight(), followObject: { id: 'fast', parent: 'host' }, followCamera: true };
  const controls = { target: new THREE.Vector3(), update: vi.fn() };
  const meshes = new Map([['host', host], ['fast', fast], ['fallback', fallback]]);
  const stop = startAnimationLoop({ state, camera, controls, renderer, scene: new THREE.Scene(), meshes,
    solar: [{ id: 'host', kind: 'planet', au: 1 }, { id: 'missing' }, { id: 'm', kind: 'moon' }],
    moons: [{ pivot, mesh: moon, obj: {}, parentId: 'host' }],
    localOrbits: [
      { mesh: fast, parent: host, basis: [1, 0, 0, 0, 0, 1], radius: 3, phase: .2, period: 20 },
      { mesh: fallback, parentId: 'host', frame: orbitFrame('host'), radius: 3, phase: .2, period: 20 },
      { mesh: new THREE.Object3D(), parentId: 'missing' },
    ], blackHolesList: [{ disk, lensHalo, photonRing }, {}], labels: [{ label, mesh: host, id: 'host' }] });
  const snapshot = () => [fast.position.toArray(), fallback.position.toArray(), pivot.rotation.y, disk.rotation.z];
  const initial = snapshot();
  expect(state.focusLight.intensity).toBe(6); expect(label.visible).toBe(true);
  expect(pivot.position.toArray()).toEqual(host.position.toArray());
  state.simTime += 86400000; tick(); expect(snapshot()).not.toEqual(initial);
  state.simTime -= 86400000; tick(); expect(snapshot()).toEqual(initial);
  state.view = 'local'; state.followObject = null; tick();
  expect(label.visible).toBe(false); expect(state.focusLight.intensity).toBe(0);
  state.followObject = { id: 'host' }; state.followCamera = false; state.view = 'solar'; tick();
  expect(label.visible).toBe(false); expect(state.lastFollowPos).toBe(null);
  expect(console.log).toHaveBeenCalled(); stop(); delete window.__astroverseLodDebug;
});
