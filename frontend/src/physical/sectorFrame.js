/** Validated positions/1 frames; assembly stays private until manager publication. */
import { verifiedRows, yieldPhysicalWork } from './coordinates.js';

const fail = message => { throw new Error(message); };

export const POSITION_COORDINATE_FIELDS = Object.freeze([
  'reference_system', 'origin', 'unit', 'time_scale',
  'corrections', 'representation', 'axes', 'position_type',
]);
export const validPositionId = id => typeof id === 'string' && id.length > 0 && id.length <= 512;

export function validatePositionFrame(body, milliseconds) {
  verifiedRows(body);
  if (typeof body.revision !== 'string' || !body.revision || body.revision.length > 256
      || body.coordinates.revision !== body.revision) fail('Некорректная ревизия положений');
  if (Date.parse(body.evaluated_at) !== milliseconds) fail('Эфемерида относится к другому моменту');
  if (body.registry_revision !== undefined && (typeof body.registry_revision !== 'string'
      || !body.registry_revision || body.registry_revision.length > 256)) fail('Некорректная ревизия реестра');
  const ids = new Set(), targets = new Set();
  for (const row of body.objects) {
    if (!validPositionId(row.id) || ids.has(row.id)) fail('Дубликат или неверный ID физического тела');
    ids.add(row.id);
    if (row.status === 'unknown' ? row.position !== null : row.status !== 'computed'
        || !Array.isArray(row.position) || row.position.length !== 3 || !row.position.every(Number.isFinite)) fail('Некорректное положение тела');
    if (row.target != null) {
      const identity = JSON.stringify([row.model_id ?? null, row.target]);
      if (targets.has(identity)) fail('Дубликат идентичности физического тела');
      targets.add(identity);
    }
  }
}

export function combinePositionFrames(manifest, bodies, milliseconds) {
  if (bodies.length === 1) return bodies[0]; // Keep the compatible single-sector wire shape.
  const frame = {...manifest, objects:bodies.flatMap(body => body.objects)};
  delete frame.sector;
  if (bodies.some(body => body.hierarchy)) {
    if (bodies.some(body => !body.hierarchy)) fail('Несовместимая физическая иерархия');
    frame.hierarchy = {...bodies[0].hierarchy};
    for (const key of ['sectors','systems','bodies']) {
      const rows = new Map();
      for (const body of bodies) for (const row of body.hierarchy[key]) {
        if (rows.has(row.id) && JSON.stringify(rows.get(row.id)) !== JSON.stringify(row)) fail('Конфликт физических адресов');
        rows.set(row.id, row);
      }
      frame.hierarchy[key] = [...rows.values()];
    }
  }
  validatePositionFrame(frame, milliseconds); // Global IDs, source identities and parent closure.
  return frame;
}

// Sector payloads have already passed bounded contract/time validation. Global
// identity closure and array assembly are staged, never published piecemeal.
export async function combineLargePositionFrames(manifest, bodies, check, onSlice) {
  if (bodies.some(body => body.hierarchy)) throw new Error('Large hierarchy exceeds decoder budget');
  const objects = [], ids = new Set(), targets = new Set();
  for (const body of bodies) {
    for (let offset = 0; offset < body.objects.length;) {
      await yieldPhysicalWork();
      check();
      const start = performance.now();
      let count = 0;
      while (offset < body.objects.length && count++ < 500 && performance.now() - start < 2) {
        const row = body.objects[offset++];
        if (ids.has(row.id)) fail('Дубликат или неверный ID физического тела');
        ids.add(row.id);
        if (row.target != null) {
          const identity = JSON.stringify([row.model_id ?? null, row.target]);
          if (targets.has(identity)) fail('Дубликат идентичности физического тела');
          targets.add(identity);
        }
        objects.push(row);
      }
      onSlice(performance.now() - start);
    }
  }
  check();
  const frame = {...manifest, objects};
  delete frame.sector;
  return frame;
}
