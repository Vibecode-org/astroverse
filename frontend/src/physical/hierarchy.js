/** Bounded translation-only charts in canonical ICRF/SSB/km at ONE instant.
 * Hierarchy epochs describe evaluation, never a fabricated source catalog epoch.
 * Source vectors remain authoritative; local offsets must agree within binary64
 * arithmetic roundoff. That tolerance is not astronomical source uncertainty.
 */
const fail = () => { throw new Error('Некорректная физическая иерархия'); };
const vector = value => value === null || (Array.isArray(value) && value.length === 3 && value.every(Number.isFinite));
const id = value => typeof value === 'string' && value.length > 0 && value.length <= 512;
const sum = (...vectors) => vectors.some(v => v === null) ? null : [0,1,2].map(a => vectors.reduce((n,v)=>n+v[a],0));
const difference = (a,b) => a.map((v,i)=>v-b[i]);

export class PhysicalHierarchy {
  constructor(frame) {
    const h = frame.hierarchy, c = frame.coordinates;
    if (!h || h.version !== 'physical-hierarchy/1' || typeof frame.revision !== 'string'
      || h.revision !== frame.revision || c.revision !== frame.revision || h.jd_tdb !== frame.jd_tdb
      || h.evaluated_at !== frame.evaluated_at || !Number.isFinite(h.jd_tdb)
      || h.reference_system !== 'ICRF' || h.origin !== 'solar_system_barycenter'
      || h.unit !== 'km' || h.time_scale !== 'TDB'
      || ['reference_system','origin','unit','time_scale'].some(key=>h[key] !== c[key])) fail();
    this.sectors = this.index(h.sectors, 128, 'origin_km');
    this.systems = this.index(h.systems, 512, 'offset_km');
    this.bodies = this.index(h.bodies, 4096, 'offset_km');
    for (const row of this.systems.values()) if (!this.sectors.has(row.sector_id)) fail();
    for (const row of this.bodies.values()) {
      const unlocated = row.system_id === null && row.offset_km === null;
      if (!unlocated && !this.systems.has(row.system_id)) fail();
    }
    if (!Array.isArray(frame.objects) || frame.objects.length !== this.bodies.size) fail();
    const seen = new Set();
    for (const row of frame.objects) {
      if (seen.has(row.id) || !this.bodies.has(row.id) || !vector(row.position)) fail();
      seen.add(row.id);
      const resolved = this.absolute(row.id);
      if ((resolved === null) !== (row.position === null)) fail();
      if (resolved !== null) {
        const [sector,system,body] = this.path(row.id);
        for (let a=0; a<3; a++) {
          const magnitude = Math.abs(sector.origin_km[a]) + Math.abs(system.offset_km[a])
            + Math.abs(body.offset_km[a]) + Math.abs(row.position[a]);
          const roundoff = 8 * Number.EPSILON * Math.max(1,magnitude);
          if (!Number.isFinite(magnitude) || !Number.isFinite(resolved[a]) || Math.abs(resolved[a]-row.position[a]) > roundoff) fail();
        }
      }
    }
    this.binding = Object.freeze({ revision:h.revision, jd_tdb:h.jd_tdb, evaluated_at:h.evaluated_at });
  }

  index(rows, limit, field) {
    if (!Array.isArray(rows) || rows.length > limit) fail();
    const result = new Map();
    for (const row of rows) {
      if (!row || !id(row.id) || result.has(row.id) || !vector(row[field])) fail();
      result.set(row.id, Object.freeze({id:row.id, sector_id:row.sector_id, system_id:row.system_id, [field]:row[field] === null ? null : Object.freeze([...row[field]])}));
    }
    return result;
  }

  path(objectId) {
    const body = this.bodies.get(objectId);
    if (!body || body.system_id === null) return null;
    const system = this.systems.get(body.system_id);
    return [this.sectors.get(system.sector_id), system, body];
  }

  absolute(objectId) {
    const path = this.path(objectId);
    return path ? sum(path[0].origin_km,path[1].offset_km,path[2].offset_km) : null;
  }

  relative(objectId, originId) {
    const a = this.path(objectId), b = this.path(originId);
    if (!a || !b || [a,b].some(path=>path[0].origin_km === null || path[1].offset_km === null || path[2].offset_km === null)) return null;
    const local = difference(a[2].offset_km,b[2].offset_km);
    if (a[1].id === b[1].id) return local;
    const system = difference(a[1].offset_km,b[1].offset_km);
    if (a[0].id === b[0].id) return sum(system,local);
    return sum(difference(a[0].origin_km,b[0].origin_km),system,local);
  }

  address(objectId) {
    const path = this.path(objectId);
    return path ? {sector_id:path[0].id, system_id:path[1].id, id:objectId} : null;
  }
}
