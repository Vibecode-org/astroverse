import { it, expect } from 'vitest';
import * as THREE from 'three';
import { createPhysicalLayer, LOD_LIMITS } from '../src/physical/physicalLayer.js';
const frame=n=>({version:'positions/1',jd_tdb:2451545,coordinates:{representation:'simulation_position',unit:'km',reference_system:'ICRF',origin:'solar_system_barycenter',time_scale:'TDB',corrections:'NONE'},objects:Array.from({length:n},(_,i)=>({id:String(i),status:'computed',position:[i*100,0,0]}))});
const camera=z=>{const c=new THREE.PerspectiveCamera(50,1,.01,10000);c.position.z=z;c.lookAt(0,0,0);c.updateMatrixWorld();return c;};
it('bounds work and detail, prioritizes selection, preserves all centers and reuses stable slots',()=>{
 const scene=new THREE.Scene(),layer=createPhysicalLayer(scene),f=frame(4096),raw=JSON.stringify(f);
 layer.update(f,'0',true);const before=layer.inspect(),c=camera(10);
 layer.tick(c);expect(layer.stats().visited).toBe(128);expect(layer.stats().detailed).toBe(32);
 layer.update(f,'0',true,null,[],'4095');layer.tick(c);
 expect(layer.stats().assignments.at(-1).level).toBe(1);expect(layer.stats().detailed).toBe(32);
 expect(layer.inspect()).toEqual(before);expect(JSON.stringify(f)).toBe(raw);
 expect(layer.stats().bufferBytes).toBe(4096*28);
 const subset={...f,objects:[f.objects[1],f.objects[4095]]};layer.update(subset,'0',true);
 expect(layer.stats().assignments.map(x=>x.slot)).toEqual([1,4095]);
 subset.objects.push({id:'new',status:'computed',position:[1,2,3]});layer.update(subset,'0',true);
 expect(layer.stats().assignments.at(-1).slot).toBe(0);
 expect(scene.children).toHaveLength(1);layer.dispose();
});
it('hysteresis and picking agree across levels; pending scans never carry old time or membership',()=>{
 const layer=createPhysicalLayer(new THREE.Scene()),f=frame(1),c=camera(19);
 layer.update(f,'0',true);layer.tick(c);expect(layer.stats().detailed).toBe(1);
 const original=layer.inspect();
 for(const z of [21,27,20,27]){c.position.z=z;layer.tick(c);expect(layer.stats().detailed).toBe(1);expect(layer.pick(c,300,300,600,600)).toBe('0');}
 c.position.z=29;layer.tick(c);expect(layer.stats().detailed).toBe(0);expect(layer.pick(c,300,300,600,600)).toBe('0');
 expect(layer.pick(c,0,0,600,600)).toBe(null);expect(layer.inspect()).toEqual(original);
 c.position.z=-29;expect(layer.pick(c,300,300,600,600)).toBe(null);
 layer.update(frame(300),'0',true);layer.tick(c);layer.update(null);layer.tick(c);
 expect(layer.stats().visited).toBe(0);expect(layer.stats().slots).toBe(0);
 layer.update({...f,jd_tdb:2451546},'0',true);c.position.z=19;layer.tick(c);expect(layer.stats().detailed).toBe(1);
 expect(()=>layer.update({...f,objects:[...f.objects,...f.objects]},'0',true)).toThrow();
 expect(LOD_LIMITS.objects).toBe(4096);layer.dispose();
});

import horizons from '../../tests/fixtures/horizons_centers.json';
it('all 100 Horizons vectors remain bit-identical through every marker transition',()=>{
 const layer=createPhysicalLayer(new THREE.Scene());let count=0;
 for(const sample of horizons.samples)for(const row of sample.rows){
   const f={...frame(0),jd_tdb:row.jd_tdb,objects:[{id:sample.id,status:'computed',position:[...row.position]}]};
   layer.update(f,sample.id,true);const before=layer.inspect();
   for(const z of [19,23,29,23,19]){layer.tick(camera(z));expect(layer.inspect()).toEqual(before);expect(layer.inspect().rows[0].position).toEqual(row.position);}
   count++;
 }
 expect(count).toBe(100);layer.dispose();
});
it('continuous frame replacement cannot starve the tail of the bounded LOD scan',()=>{
 const layer=createPhysicalLayer(new THREE.Scene()),f=frame(4096),c=camera(10);
 f.objects.forEach((row,i)=>{row.position=[i<4000?1e9:0,0,0];});
 for(let i=0;i<40;i++){layer.update({...f,jd_tdb:2451545+i},'missing',true);layer.tick(c);}
 expect(layer.stats().detailed).toBe(32);
 expect(layer.stats().assignments.filter(x=>x.level).every(x=>Number(x.id)>=4000)).toBe(true);layer.dispose();
});
it('scales marker pixels for Retina without changing centers, levels or CSS picking',()=>{
 const scene=new THREE.Scene(),layer=createPhysicalLayer(scene),c=camera(19);
 layer.update(frame(1),'0',true);layer.tick(c);const before=layer.inspect();
 layer.tick(c,2);expect(scene.children[0].material.uniforms.markerPixelRatio.value).toBe(2);
 expect(layer.pick(c,300,300,600,600)).toBe('0');expect(layer.inspect()).toEqual(before);layer.dispose();
});
it('preserves slot identity and exact centers under deterministic membership/time/camera churn',()=>{
 const scene=new THREE.Scene(),layer=createPhysicalLayer(scene);let seed=7123,previous=new Map();
 const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed;};
 for(let step=0;step<150;step++){
  const objects=Array.from({length:200},(_,i)=>i).filter(()=>random()%3!==0).map(i=>({id:String(i),status:'computed',position:[i*1000,step*100,0]}));
  const f={...frame(0),jd_tdb:2451545+step,objects},raw=JSON.stringify(f);
  layer.update(f,'missing',true,null,[],objects[0]?.id);layer.tick(camera(random()%100));
  const stats=layer.stats();expect(stats.detailed).toBeLessThanOrEqual(32);expect(stats.visited).toBeLessThanOrEqual(128);
  expect(new Set(stats.assignments.map(x=>x.slot)).size).toBe(objects.length);
  for(const row of stats.assignments)if(previous.has(row.id))expect(row.slot).toBe(previous.get(row.id));
  expect(layer.inspect().rows.map(r=>r.position)).toEqual(objects.map(r=>r.position));expect(JSON.stringify(f)).toBe(raw);
  previous=new Map(stats.assignments.map(x=>[x.id,x.slot]));
 }
 expect(scene.children).toHaveLength(1);layer.dispose();
});
