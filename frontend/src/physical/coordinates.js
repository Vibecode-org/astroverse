import { PhysicalHierarchy } from './hierarchy.js';

/** Float64 physical km -> render. One linear scale, rotation only, floating origin. */
export const KM_PER_RENDER_UNIT = 100000;
export function renderPosition(position, origin, kmPerUnit = KM_PER_RENDER_UNIT) {
  if (!(kmPerUnit > 0) || !Number.isFinite(kmPerUnit)) throw new Error('invalid linear scale');
  if (![position, origin].every(v => Array.isArray(v) && v.length === 3 && v.every(Number.isFinite))) {
    throw new Error('unknown position');
  }
  // ICRF right-handed XYZ -> right-handed Y-up X,Z,-Y.
  return [(position[0] - origin[0]) / kmPerUnit,
    (position[2] - origin[2]) / kmPerUnit, -(position[1] - origin[1]) / kmPerUnit];
}
export function physicalFrame(frame) {
  const c = frame?.coordinates;
  if (frame?.version !== 'positions/1' || c?.representation !== 'simulation_position'
      || c.unit !== 'km' || c.reference_system !== 'ICRF' || c.origin !== 'solar_system_barycenter'
      || c.time_scale !== 'TDB' || c.corrections !== 'NONE' || !Number.isFinite(frame.jd_tdb)) throw new Error('Неподдерживаемый контракт положений');
  const hierarchy = frame.hierarchy === undefined ? null : new PhysicalHierarchy(frame);
  const rows = frame.objects.filter(row => row.status === 'computed' && Array.isArray(row.position)
    && row.position.length === 3 && row.position.every(Number.isFinite));
  return { rows, hierarchy };
}
export function verifiedRows(frame) { return physicalFrame(frame).rows; }

/** Camera render offset -> ICRF km relative to the selected moving origin. */
export function physicalOffset(render) {
  return [render.x * KM_PER_RENDER_UNIT, -render.z * KM_PER_RENDER_UNIT, render.y * KM_PER_RENDER_UNIT];
}
