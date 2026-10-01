/** Deterministic string hash in [0, 1).
 *
 * Positions, orbital planes and phases are derived from an object's id so that
 * the scene is identical on every rebuild — `Math.random()` here would make
 * objects jump each time the scene is re-mounted. The implementation (FNV-1a)
 * is fixed: changing it reshuffles every generated position in the catalog.
 */
export function hashUnit(seed) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 1000003) / 1000003;
}
