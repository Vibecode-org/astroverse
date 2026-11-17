import { describe,expect,it } from 'vitest';
import { Vector3, SphereGeometry } from 'three';
import { BODY_IDS,getBodyModel,bodyAngles,bodyOrientation,sunlightDirection } from '../src/physical/bodyModel.js';

describe('five pinned spherical body models',()=>{
  it('keeps measured size independent of render markers, with no unknown fallback',()=>{
    expect(BODY_IDS).toEqual(['sun','earth','moon','mercury','venus']);
    expect(getBodyModel('sun').radiusKm).toBe(695700);
    expect(getBodyModel('earth').radiusKm).toBeCloseTo(6371.008366666667,10);
    expect(getBodyModel('mercury').radiusKm).toBeCloseTo(2439.773333333333,10);
    expect(getBodyModel('moon').radiusKm).toBeCloseTo(1737.4,10);
    expect(getBodyModel('venus').radiusKm).toBeCloseTo(6051.8,10);
    expect(getBodyModel('unknown')).toBeNull();
    expect(getBodyModel('__proto__')).toBeNull();
  });
  it('uses TDB epoch and correct prograde/retrograde signs',()=>{
    expect(bodyAngles('earth',2451545)).toEqual({ra:0,dec:90,w:190.147});
    expect(bodyAngles('earth',2451546).w-bodyAngles('earth',2451545).w).toBeCloseTo(360.9856235,9);
    expect(bodyAngles('venus',2451546).w-bodyAngles('venus',2451545).w).toBeCloseTo(-1.4813688,10);
    expect(bodyAngles('moon',2451546).w-bodyAngles('moon',2451545).w).toBeCloseTo(13.17635815,9);
    expect(bodyOrientation('earth',NaN)).toBeNull();
    expect(bodyOrientation('earth',2462502.5)).toBeNull();
  });
  it('matches independent J2000 Earth meridian/pole directions and right handedness',()=>{
    const q=bodyOrientation('earth',2451545);
    // RA=0 DEC=90: ascending node is ICRF +Y; W=190.147 from that node.
    const w=190.147*Math.PI/180;
    const prime=new Vector3(1,0,0).applyQuaternion(q);
    expect(prime.x).toBeCloseTo(-Math.sin(w),13);
    expect(prime.y).toBeCloseTo(0,13);
    expect(prime.z).toBeCloseTo(-Math.cos(w),13);
    expect(new Vector3(0,1,0).applyQuaternion(q).distanceTo(new Vector3(0,1,0))).toBeLessThan(1e-14);
    for(const id of BODY_IDS){
      const orientation=bodyOrientation(id,2460000);
      expect(orientation.length()).toBeCloseTo(1,14);
      const x=new Vector3(1,0,0).applyQuaternion(orientation), y=new Vector3(0,1,0).applyQuaternion(orientation);
      const z=new Vector3(0,0,1).applyQuaternion(orientation);
      expect(x.clone().cross(y).distanceTo(z)).toBeLessThan(1e-14);
    }
  });
  it('aligns actual THREE UV geometry with the documented east-positive maps',()=>{
    const geometry=new SphereGeometry(1,8,4);
    const uv=geometry.attributes.uv,position=geometry.attributes.position;
    for(let i=0;i<uv.count;i++){
      if(uv.getY(i)!==.5)continue;
      if(uv.getX(i)===.5)expect(new Vector3().fromBufferAttribute(position,i).distanceTo(new Vector3(1,0,0))).toBeLessThan(1e-7);
      if(uv.getX(i)===.75)expect(new Vector3().fromBufferAttribute(position,i).distanceTo(new Vector3(0,0,-1))).toBeLessThan(1e-7);
    }
    geometry.dispose();
  });
  it('lights the Sun-facing hemisphere with origin-invariant center differences',()=>{
    const direction=sunlightDirection([11,22,33],[14,26,33]);
    expect(direction.distanceTo(new Vector3(.6,0,-.8))).toBeLessThan(1e-15);
    expect(sunlightDirection([1,2,3],[1,2,3])).toBeNull();
    expect(sunlightDirection(null,[0,0,0])).toBeNull();
    expect(sunlightDirection([1e8+11,1e8+22,1e8+33],[1e8+14,1e8+26,1e8+33]).distanceTo(direction)).toBe(0);
  });
});
