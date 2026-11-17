import { Matrix4, Quaternion, Vector3 } from 'three';

// Pinned numeric subset of NAIF pck00011.tpc (2022-12-27), ICRF/TDB.
// https://naif.jpl.nasa.gov/pub/naif/generic_kernels/pck/pck00011.tpc
// Spheres use arithmetic mean of its three shape axes, not terrain radii.
const definitions = {
  sun: [10, [695700,695700,695700], [286.13,0], [63.87,0], [84.176,14.18440,0]],
  earth: [399, [6378.1366,6378.1366,6356.7519], [0,-0.641], [90,-0.557], [190.147,360.9856235,0]],
  moon: [301, [1737.4,1737.4,1737.4], [269.9949,0.0031], [66.5392,0.0130], [38.3213,13.17635815,-1.4e-12]],
  mercury: [199, [2440.53,2440.53,2438.26], [281.0103,-0.0328], [61.4155,-0.0049], [329.5988,6.1385108,0]],
  venus: [299, [6051.8,6051.8,6051.8], [272.76,0], [67.16,0], [160.20,-1.4813688,0]],
};
export const BODY_IDS = Object.freeze(Object.keys(definitions));
const models = Object.fromEntries(BODY_IDS.map(id => {
  const [naifId,axes,ra,dec,pm] = definitions[id];
  return [id,Object.freeze({id,naifId,radiusKm:axes.reduce((a,b)=>a+b,0)/3,
    axesKm:Object.freeze(axes),poleRa:Object.freeze(ra),poleDec:Object.freeze(dec),
    primeMeridian:Object.freeze(pm),orientationModel:'pck00011-polynomial-only',
    accuracy:null})];
}));
export function getBodyModel(id) { return Object.hasOwn(models,id) ? models[id] : null; }
const radians = degrees => (degrees % 360) * Math.PI / 180;

/** Approximate IAU polynomial angles; no Moon/Mercury periodic terms or EOP.
 * d = TDB days from J2000; T = Julian centuries. W increases eastward.
 * This deliberately makes no claim to full PCK or DE440 orientation accuracy.
 */
export function bodyAngles(id,jdTdb) {
  const model=getBodyModel(id);
  if(!model || !Number.isFinite(jdTdb) || jdTdb<2451544.5 || jdTdb>=2462502.5) return null;
  const d=jdTdb-2451545,T=d/36525;
  return {ra:model.poleRa[0]+model.poleRa[1]*T,
    dec:model.poleDec[0]+model.poleDec[1]*T,
    w:model.primeMeridian[0]+model.primeMeridian[1]*d+model.primeMeridian[2]*d*d};
}

/** Sphere local +Y=north, +X=longitude 0, -Z=east longitude 90 degrees.
 * Standard THREE SphereGeometry: u=.5 prime, u=.75 east90, v=1 north.
 * Body axes are rotated into ICRF, then into render (X,Z,-Y); no position/scale.
 */
export function bodyOrientation(id,jdTdb) {
  const angles=bodyAngles(id,jdTdb); if(!angles) return null;
  const a=radians(angles.ra),delta=radians(angles.dec),w=radians(angles.w);
  const pole=new Vector3(Math.cos(delta)*Math.cos(a),Math.cos(delta)*Math.sin(a),Math.sin(delta));
  const node=new Vector3(-Math.sin(a),Math.cos(a),0);
  const transverse=new Vector3().crossVectors(pole,node);
  const prime=node.clone().multiplyScalar(Math.cos(w)).addScaledVector(transverse,Math.sin(w));
  const east=node.clone().multiplyScalar(-Math.sin(w)).addScaledVector(transverse,Math.cos(w));
  const render=v=>new Vector3(v.x,v.z,-v.y);
  return new Quaternion().setFromRotationMatrix(new Matrix4().makeBasis(render(prime),render(pole),render(east).negate())).normalize();
}

/** Geometric body->Sun direction from same-frame/time Float64 ICRF km centers.
 * No light time, aberration, eclipses, inverse-square intensity or shadows.
 */
export function sunlightDirection(bodyPositionKm,sunPositionKm) {
  if(![bodyPositionKm,sunPositionKm].every(v=>Array.isArray(v)&&v.length===3&&v.every(Number.isFinite)))return null;
  const d=sunPositionKm.map((n,i)=>n-bodyPositionKm[i]);
  if(!d.every(Number.isFinite)||Math.hypot(...d)===0)return null;
  return new Vector3(d[0],d[2],-d[1]).normalize();
}
