import { describe, it, expect, vi } from 'vitest';
import * as THREE from 'three';
import { renderPosition, verifiedRows } from '../src/physical/coordinates.js';
import { createPhysicalLayer } from '../src/physical/PhysicalScene.jsx';

const coordinates = { representation: 'simulation_position', unit: 'km', reference_system: 'ICRF', origin: 'solar_system_barycenter', corrections: 'NONE', time_scale: 'TDB' };
const frame = objects => ({ version: 'positions/1', coordinates, jd_tdb: 2451545, objects });
const row = (id, position) => ({ id, position, status: 'computed' });

describe('physical centers', () => {
  it('preserves distances through floating origin, axis rotation and linear scales', () => {
    const a = [149597870.7, -2e6, 9e7], b = [149897870.7, -2e6 + 300, 9e7 - 50];
    const distance = Math.hypot(...a.map((x, i) => x - b[i]));
    for (const origin of [[0,0,0],a,b,[1e12,2e12,-3e12]]) for (const scale of [1,1000,1e5]) {
      const ra = renderPosition(a, origin, scale), rb = renderPosition(b, origin, scale);
      expect(Math.hypot(...ra.map((x,i) => (x-rb[i])*scale))).toBeCloseTo(distance, 2);
    }
    expect(renderPosition([10,20,30],[0,0,0],10)).toEqual([1,3,-2]);
    for (const scale of [0,-1,NaN,Infinity]) expect(() => renderPosition(a,b,scale)).toThrow();
    for (const pos of [null,[1,2],[1,2,NaN]]) expect(() => renderPosition(pos,b)).toThrow();
  });
  it('rejects snapshot/render contracts and keeps unknown positions out', () => {
    expect(verifiedRows(frame([row('a',[1,2,3]),row('b',null),row('c',[NaN,0,0]),{ status:'unknown' }]))).toHaveLength(1);
    for (const bad of [null, { version:'coordinates/1' }, { ...frame([]), jd_tdb:NaN },
      ...['representation','unit','reference_system','origin','corrections'].map(field => ({...frame([]),coordinates:{...coordinates,[field]:'wrong'}}))]) {
      expect(() => verifiedRows(bad)).toThrow();
    }
  });
  it('loads and evicts centers without rebuilding resources or changing physical vectors', () => {
    const scene = new THREE.Scene(), layer = createPhysicalLayer(scene);
    const value = frame([row('earth',[1e8,3e7,0]),row('moon',[1e8+300000,3e7,0]),row('sun',[0,0,0])]);
    const original = JSON.stringify(value);
    const points = scene.children[0], geometry = points.geometry;
    layer.update(value,'earth'); expect(geometry.drawRange.count).toBe(3);
    const near = layer.inspect();
    layer.update(value,'earth',true); expect(geometry.drawRange.count).toBe(3);
    expect(layer.inspect().render).toEqual(near.render);
    layer.update(value,'sun'); expect(layer.inspect().rows.map(r => r.id)).toEqual(['earth','moon','sun']);
    layer.update(value,'missing',true); expect(layer.inspect().origin).toEqual([0,0,0]);
    layer.update(frame([row('extra',[0,0,0])]),'extra',true);
    layer.update(frame([1,2,3,4,5,6].map(n => row(String(n),[n,0,0]))),'1');
    layer.update(null); expect(points.visible).toBe(false); expect(geometry.drawRange.count).toBe(0);
    expect(scene.children[0].geometry).toBe(geometry); expect(JSON.stringify(value)).toBe(original);
    const dispose=vi.spyOn(geometry,'dispose'); layer.dispose(); expect(dispose).toHaveBeenCalledOnce(); expect(scene.children).toHaveLength(0);
  });
  it('grows a bounded reusable buffer for explicitly synthetic membership', () => {
    const scene = new THREE.Scene(), layer = createPhysicalLayer(scene);
    const points = scene.children[0], material = points.material, original = points.geometry;
    const disposed = vi.spyOn(original, 'dispose');
    const objects = Array.from({length:129}, (_,i)=>row(`synthetic-${i}`,[i,0,0]));
    layer.update(frame(objects),'synthetic-0',true,null,[{id:'synthetic-0',color:'#ff0000'}]);
    expect(disposed).toHaveBeenCalledOnce();
    const grown = points.geometry;
    expect(grown.attributes.position.count).toBe(256);
    expect(grown.attributes.color.array[0]).toBe(1);
    for(let i=0;i<20;i++) {
      layer.update(frame(objects.slice(0,10)),'synthetic-0',true);
      layer.update(null);
      layer.update(frame(objects),'synthetic-0',true);
      expect(points.geometry).toBe(grown); expect(points.material).toBe(material);
    }
    expect(()=>layer.update(frame(Array.from({length:4097},()=>row('synthetic',[0,0,0]))),'synthetic',true)).toThrow();
    const finalDispose = vi.spyOn(grown,'dispose'); layer.dispose();
    expect(finalDispose).toHaveBeenCalledOnce();
  });
  it('holds five centers and follows Mercury/Venus through eviction without altering any vector', () => {
    const value = frame([row('sun',[0,0,0]),row('earth',[1e8,0,0]),row('moon',[1e8+3e5,0,0]),
      row('mercury',[3e7,4e7,1e6]),row('venus',[-9e7,5e7,-1e6])]);
    const original = JSON.stringify(value), scene = new THREE.Scene(), layer = createPhysicalLayer(scene);
    const geometry = scene.children[0].geometry;
    for (const id of ['mercury','venus']) {
      layer.update(value,id,true);
      expect(geometry.drawRange.count).toBe(5);
      const all = layer.inspect();
      expect(all.origin).toEqual(value.objects.find(row=>row.id===id).position);
      layer.update(value,id);
      expect(layer.inspect().rows).toEqual(all.rows);
      layer.update(value,id,false,{offset:[1e12,0,0],radius:1});
      expect(geometry.drawRange.count).toBe(5);
      // Only an empty manager frame evicts the resident centers.
      layer.update({...value,objects:[]},id);
      expect(geometry.drawRange.count).toBe(0);
      layer.update(value,id,true);
      expect(layer.inspect()).toEqual(all);
      expect(scene.children[0].geometry).toBe(geometry);
    }
    expect(JSON.stringify(value)).toBe(original);layer.dispose();
  });

});


it('rejects missing and incompatible time scales even in flat positions/1',()=>{
  const value=frame([row('earth',[1,2,3])]);
  for(const scale of ['UTC','TT',null,undefined]) {
    expect(()=>verifiedRows({...value,coordinates:{...coordinates,time_scale:scale}})).toThrow('контракт');
  }
  expect(verifiedRows(value)).toHaveLength(1);
});
