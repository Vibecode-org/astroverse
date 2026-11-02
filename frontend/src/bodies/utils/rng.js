/** Deterministic PRNG for procedural geometry (K-5).
 *
 * The scene is rebuilt on every mount, so `Math.random()` would move stars,
 * belts and nebula clouds between rebuilds. A fixed 32-bit LCG seeded by a
 * string or number keeps every generated position byte-for-byte identical.
 */

import { hashUnit } from './hash.js';

export function makeSeededRng(seed) {
  let state = typeof seed === 'number'
    ? (seed >>> 0)
    : (Math.floor(hashUnit(String(seed)) * 0xffffffff) >>> 0);
  if (state === 0) state = 0x9e3779b9;
  return function rng() {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}
