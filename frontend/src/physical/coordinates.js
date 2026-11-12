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

export function relativeToReference(row, hierarchy, reference) {
  const path = hierarchy?.path(row.id), base = reference.path;
  // Subtract each chart component before summing, including across time/address
  // changes. This retains supplied sub-ULP local offsets at large common origins.
  return [0,1,2].map(a => (path && base
    ? (path[0].origin_km[a]-base[0].origin_km[a])
      +(path[1].offset_km[a]-base[1].offset_km[a])
      +(path[2].offset_km[a]-base[2].offset_km[a])
    : row.position[a]-reference.position[a])-reference.offset[a]);
}

// Large flat synthetic frames use the same contract, filtering in cancellable
// slices. Hierarchical production frames retain their stricter bounded decoder.
export async function physicalFrameAsync(frame, check, onSlice, centerId) {
  if (frame.hierarchy !== undefined || frame.objects.length <= 4096) return physicalFrame(frame);
  physicalFrame({...frame,objects:[]});
  const rows=[];let centerPosition=null;
  for(let offset=0;offset<frame.objects.length;){
    await yieldPhysicalWork();check();
    const start=performance.now();let count=0;
    while(offset<frame.objects.length && count++<500 && performance.now()-start<2){
      const row=frame.objects[offset++];
      if(row.id===centerId)centerPosition=row.position;
      if(row.status==='computed' && Array.isArray(row.position) && row.position.length===3 && row.position.every(Number.isFinite))rows.push(row);
    }
    onSlice?.(performance.now()-start);
  }
  check();return {rows,hierarchy:null,centerPosition};
}

// All manager/renderer continuations share a 2ms wall-time allowance between
// RAFs. scheduler.yield alone can saturate the task queue during continuous
// updates. Each operation remains bounded; this gate limits the aggregate duty.
let workDeadline=0;
export const yieldPhysicalWork = () => {
  if(!globalThis.scheduler?.yield || !globalThis.requestAnimationFrame)
    return new Promise(resolve=>setTimeout(resolve,0));
  if(performance.now()<workDeadline)return globalThis.scheduler.yield();
  return new Promise(resolve=>{
    let raf,timer;
    const resume=()=>{clearTimeout(timer);cancelAnimationFrame(raf);workDeadline=performance.now()+2;resolve();};
    raf=requestAnimationFrame(resume);
    // Hidden tabs must still drain cancelled staging/workers.
    timer=setTimeout(resume,32);
  });
};
