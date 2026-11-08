import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

// Canvas rasterization and WebGL are verified by Chrome smoke tests. Unit
// tests exercise real Three.js geometry/materials with a deterministic 2D API.
HTMLCanvasElement.prototype.getContext = function () {
  const gradient = { addColorStop: vi.fn() };
  return new Proxy({
    canvas: this,
    createRadialGradient: () => gradient,
    createLinearGradient: () => gradient,
    measureText: text => ({ width: String(text).length * 8 }),
    getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
    createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
  }, { get: (target, key) => key in target ? target[key] : () => {} });
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
