import { expect, test, vi } from 'vitest';
import * as THREE from 'three';
import { createStage } from '../src/scene/stage.js';

vi.mock('three', async original => {
  const actual = await original();
  return { ...actual, WebGLRenderer: vi.fn(function () {
    this.domElement = document.createElement('canvas');
    this.setPixelRatio = vi.fn(); this.setSize = vi.fn();
  }) };
});

test('stage wires real camera/controls/lights around the renderer and replaces stale canvas', () => {
  const el = document.createElement('div'); el.appendChild(document.createElement('canvas'));
  Object.defineProperties(el, { clientWidth: { value: 800 }, clientHeight: { value: 600 } });
  const stage = createStage(el, { far: 1000, maxDistance: 500, solarCam: [1, 2, 3] });
  expect(el.children).toHaveLength(1); expect(el.firstChild).toBe(stage.renderer.domElement);
  expect(stage.camera.aspect).toBeCloseTo(800 / 600);
  expect(stage.camera.position.distanceTo(new THREE.Vector3(1, 2, 3))).toBeLessThan(1e-12);
  expect(stage.controls.maxDistance).toBe(500); expect(stage.sunLight.isPointLight).toBe(true);
  stage.controls.dispose();
});

test('zero-size viewport falls back to window dimensions and WebGL init errors propagate', () => {
  const stage = createStage(document.createElement('div'), { far: 1000, maxDistance: 500, solarCam: [0, 0, 1] });
  expect(stage.renderer.setSize).toHaveBeenCalledWith(window.innerWidth, window.innerHeight);
  stage.controls.dispose();
  THREE.WebGLRenderer.mockImplementationOnce(function () { throw new Error('WebGL unavailable'); });
  expect(() => createStage(document.createElement('div'), { solarCam: [0, 0, 1] })).toThrow('WebGL unavailable');
});
