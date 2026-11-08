import { expect, test, vi } from 'vitest';
import * as THREE from 'three';
import { getTexture, makeRingTexture } from '../src/bodies/textures/bodyTextures.js';
import { applyLimbDarkening } from '../src/bodies/meshes/starPlanetMesh.js';
import { makeLabel } from '../src/bodies/helpers/labelHelpers.js';

test('CDN textures and rings complete color-space initialization and reuse cached maps', () => {
  const load = vi.spyOn(THREE.TextureLoader.prototype, 'load').mockImplementation(function (url, onLoad, progress, onError) {
    const texture = new THREE.Texture(); onLoad?.(texture); onError?.(); return texture;
  });
  const earth = getTexture('earth', 'test-cdn');
  expect(earth.colorSpace).toBe(THREE.SRGBColorSpace);
  expect(getTexture('earth', 'test-cdn')).toBe(earth);
  const ring = makeRingTexture(); expect(makeRingTexture()).toBe(ring);
  expect(load).toHaveBeenCalledTimes(2);
});

test('procedural textures have deterministic seed-specific cache identities', () => {
  for (const name of ['rocky', 'ice', 'gas', 'lava', 'unknown']) {
    const texture = getTexture(name, 0);
    expect(getTexture(name, 0)).toBe(texture);
    expect(texture.isTexture).toBe(true);
  }
  expect(getTexture('rocky', '')).not.toBe(getTexture('rocky', 0));
});

test('limb darkening injects the lighting terms into actual Three.js shader templates', () => {
  const material = new THREE.MeshBasicMaterial(); applyLimbDarkening(material);
  const shader = { vertexShader: THREE.ShaderLib.basic.vertexShader,
    fragmentShader: THREE.ShaderLib.basic.fragmentShader };
  material.onBeforeCompile(shader);
  expect(shader.vertexShader).toContain('vAstroNormal = normalize');
  expect(shader.fragmentShader).toContain('outgoingLight *= mix');
});

test('labels also draw on browsers without CanvasRenderingContext2D.roundRect', () => {
  const original = HTMLCanvasElement.prototype.getContext;
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(function (...args) {
    const context = original.apply(this, args); context.roundRect = undefined; return context;
  });
  expect(makeLabel('fallback').material.map.isTexture).toBe(true);
});
