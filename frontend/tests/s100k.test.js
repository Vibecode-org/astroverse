import {yieldPhysicalWork} from '../src/physical/coordinates.js';
import {expect, test, vi} from 'vitest';
import * as THREE from 'three';
import {createPhysicalLayer} from '../src/physical/physicalLayer.js';
import {PhysicalSectorManager,S100K_LIMITS} from '../src/physical/sectorManager.js';
const frame=(n=100000)=>({version:'positions/1',synthetic:true,profile:'synthetic-s100k',jd_tdb:2451545,
  coordinates:{representation:'simulation_position',unit:'km',reference_system:'ICRF',origin:'solar_system_barycenter',time_scale:'TDB',corrections:'NONE'},
  objects:Array.from({length:n},(_,i)=>({id:`synthetic-${String(i).padStart(5,'0')}`,status:'computed',position:[(i%400-199.5)*4000,0,(Math.floor(i/400)-124.5)*4000]}))});
test('100k atomic preparation, identities, bounded LOD upload, numerical centers, cancellation and reuse',async()=>{
 const scene=new THREE.Scene(),layer=createPhysicalLayer(scene),f=frame();
 const before=f.objects.map(r=>[...r.position]);
 const pending=layer.prepare(f,'synthetic-origin',true,null,[],null,null);
 expect(layer.stats().slots).toBe(0);expect(await pending).toBe(true);
 const stats=layer.stats(),geometry=scene.children[0].geometry;
 expect(stats.slots).toBe(100000);expect(new Set(stats.assignments.map(r=>r.slot)).size).toBe(100000);
 expect(stats.bufferBytes).toBe(131072*28);
 const camera=new THREE.PerspectiveCamera(50,16/9,.00001,1e12);camera.position.set(0,8,24);camera.lookAt(0,0,0);camera.updateMatrixWorld();
 const inspect=layer.inspect();let inside=0;
 inspect.rows.forEach((r,i)=>{expect(r.position).toEqual(before[i]);const p=new THREE.Vector3().fromArray(inspect.render,i*3);expect(p.x).toBeCloseTo(r.position[0]/1e5,6);expect(p.y).toBeCloseTo(r.position[2]/1e5,6);p.project(camera);if(Math.abs(p.x)<=1&&Math.abs(p.y)<=1&&Math.abs(p.z)<=1)inside++;});
 expect(inside).toBe(100000);
 layer.tick(camera);const version=geometry.attributes.level.version;layer.tick(camera);expect(geometry.attributes.level.version).toBe(version);
 const p=new THREE.Vector3().fromArray(inspect.render,0).project(camera);
 expect(layer.pick(camera,(p.x+1)*960,(1-p.y)*540,1920,1080)).toBe('synthetic-00000');
 const original=layer.inspect();layer.rebase([1e7,-2e7,3e7]);
 const shifted=layer.inspect();expect(shifted.rows).toEqual(original.rows);
 shifted.render.forEach((v,i)=>expect(v).toBeCloseTo(original.render[i]-[100,300,200][i%3],6));
 const cancelled=layer.prepare(f,'synthetic-origin',true,null,[],null,null);layer.update(null);expect(await cancelled).toBe(false);expect(layer.stats().slots).toBe(0);
 await layer.prepare(f,'synthetic-origin',true,null,[],null,null);expect(scene.children[0].geometry).toBe(geometry);
 layer.dispose();expect(scene.children.length).toBe(0);
},20000);
test('large prepare rejects duplicate IDs without publishing partial data',async()=>{
 const layer=createPhysicalLayer(new THREE.Scene()),f=frame(5000);f.objects[4500].id=f.objects[0].id;
 await expect(layer.prepare(f,'synthetic-origin',true,null,[],null,null)).rejects.toThrow('Повтор');expect(layer.stats().slots).toBe(0);layer.dispose();
});
test('explicit large manager budgets retain bounded transport',()=>{
 const m=new PhysicalSectorManager({limits:S100K_LIMITS});expect(m.limits.concurrency).toBe(4);expect(m.limits.queue).toBe(128);expect(m.limits.objects).toBe(200000);
 expect(()=>new PhysicalSectorManager({limits:{sectorObjects:1001}})).toThrow();
});
test('100 sectors share time/revision, atomic failure, two-set admission and explicit cancellation',async()=>{
 let fail=false,revision='synthetic-1';const ms=Date.parse('2020-01-01T00:00:00Z');
 const body=(objects=[])=>({...frame(0),revision,registry_revision:'synthetic-registry',evaluated_at:new Date(ms).toISOString(),coordinates:{...frame(0).coordinates,revision},objects});
 const fetcher=async(url,{signal})=>{
   if(signal.aborted)throw new DOMException('cancelled','AbortError');
   const sector=url.includes('/sectors/'),n=sector?Number(url.split('/sectors/')[1].split('?')[0]):null;
   if(fail&&n===50)return new Response(JSON.stringify({detail:{message:'partial failure'}}),{status:422});
   const f=body(sector?frame(1000).objects.map((r,i)=>({...r,id:`synthetic-${n*1000+i}`})):[]);
   if(sector)f.sector=String(n);else f.sectors=Array.from({length:100},(_,i)=>({id:String(i),revision,object_count:1000}));
   return new Response(JSON.stringify(f),{status:200});
 };
 const manager=new PhysicalSectorManager({fetcher,limits:S100K_LIMITS});
 const first=await manager.load({milliseconds:ms,context:'same'});expect(first.objects.length).toBe(100000);expect(manager.inspect().residentObjects).toBe(100000);
 const second=await manager.load({milliseconds:ms,context:'same',retainPrevious:true});expect(second.objects.length).toBe(100000);expect(manager.inspect().peakObjects).toBe(200000);
 fail=true;await expect(manager.load({milliseconds:ms,context:'new'})).rejects.toThrow('partial failure');expect(manager.inspect().residentObjects).toBe(0);expect(manager.inspect().active).toBe(0);
 fail=false;const cancelled=manager.load({milliseconds:ms,context:'cancel'});manager.cancel();await expect(cancelled).rejects.toMatchObject({name:'AbortError'});
},20000);

test('cancel during global merge drains staging; next selection reuses workers',async()=>{
 const ms=Date.parse('2020-01-01T00:00:00Z');
 const make=(objects=[])=>({...frame(0),revision:'r',registry_revision:'registry',evaluated_at:new Date(ms).toISOString(),coordinates:{...frame(0).coordinates,revision:'r'},objects});
 const fetcher=async url=>{
   const sector=url.includes('/sectors/'),n=sector?Number(url.split('/sectors/')[1].split('?')[0]):0;
   const f=make(sector?frame(1000).objects.map((r,i)=>({...r,id:`s-${n*1000+i}`})):[]);
   if(sector)f.sector=String(n);else f.sectors=Array.from({length:6},(_,i)=>({id:String(i),revision:'r',object_count:1000}));
   return new Response(JSON.stringify(f));
 };
 const m=new PhysicalSectorManager({fetcher,limits:S100K_LIMITS});let slices=0;
 m.onPhase=e=>{if(e.kind==='merge_slice_cpu'&&++slices===2)m.cancel();};
 await expect(m.load({milliseconds:ms})).rejects.toMatchObject({name:'AbortError'});
 expect(m.inspect()).toMatchObject({active:0,objects:0,residentObjects:0});
 m.onPhase=null;expect((await m.load({milliseconds:ms})).objects).toHaveLength(6000);
 expect(m.inspect().peakActive).toBeLessThanOrEqual(4);
 m.cancel();expect(m.inspect().objects).toBe(0);
});

test('cancel during flat-frame validation preserves committed picking until explicit eviction',async()=>{
 const layer=createPhysicalLayer(new THREE.Scene()),f=frame(5000);
 await layer.prepare(f,'synthetic-origin',true,null,[],null,null);
 const prior=layer.inspect(10), pending=layer.prepare(frame(),'synthetic-origin',true,null,[],null,null);
 // Cancellation while async decoder is yielding must not publish its rows.
 layer.update(null);expect(await pending).toBe(false);expect(layer.timing().slots).toBe(0);
 await layer.prepare(f,'synthetic-origin',true,null,[],null,null);
 expect(layer.inspect(10)).toEqual(prior);layer.dispose();
});

test('origin moves during staging: committed picking and coordinates share the rebased frame',async()=>{
 const scene=new THREE.Scene(),layer=createPhysicalLayer(scene),f=frame(5000);
 const reference={position:[0,0,0],offset:[0,0,0],path:null};
 let moved=false;layer.onPhase=()=>{if(!moved){moved=true;reference.offset=[1e7,2e7,3e7];layer.rebase(reference.offset);}};
 await layer.prepare(f,'synthetic-origin',true,null,[],null,reference);
 const result=layer.inspect(1),expected=[f.objects[0].position[0]/1e5-100,f.objects[0].position[2]/1e5-300,200];
 result.render.forEach((v,a)=>expect(v).toBeCloseTo(expected[a],5));
 const camera=new THREE.PerspectiveCamera(50,16/9,.00001,1e12);
 camera.position.set(expected[0],expected[1]+8,expected[2]+24);camera.lookAt(...expected);camera.updateMatrixWorld();
 const p=new THREE.Vector3(...result.render).project(camera);
 expect(layer.pick(camera,(p.x+1)*960,(1-p.y)*540,1920,1080)).toBe(f.objects[0].id);
 layer.dispose();
});

test('flat staging subtracts common large origin before small reference offset',async()=>{
 const layer=createPhysicalLayer(new THREE.Scene()),f=frame(5000);
 f.objects.forEach(r=>r.position=[1e18,1e18,1e18]);
 await layer.prepare(f,'synthetic-origin',true,null,[],null,{position:[1e18,1e18,1e18],offset:[.125,.25,.5],path:null});
 expect(layer.inspect(1).render).toEqual([-.125/1e5,-.5/1e5,.25/1e5].map(Math.fround));layer.dispose();
});

test('paced scheduler shares a duty window and hidden RAF still drains',async()=>{
 vi.useFakeTimers();const yieldTask=vi.fn(async()=>{});
 vi.stubGlobal('scheduler',{yield:yieldTask});
 vi.stubGlobal('requestAnimationFrame',vi.fn(()=>123));vi.stubGlobal('cancelAnimationFrame',vi.fn());
 try{
   const hidden=yieldPhysicalWork();await vi.advanceTimersByTimeAsync(32);await hidden;
   await yieldPhysicalWork();expect(yieldTask).toHaveBeenCalled();
 }finally{vi.unstubAllGlobals();vi.useRealTimers();}
});

test('large replacement preserves survivor slots and reuses the evicted slot atomically',async()=>{
 const layer=createPhysicalLayer(new THREE.Scene()),f=frame(5000);
 await layer.prepare(f,'synthetic-origin',true,null,[],null,null);
 const before=layer.stats().assignments;
 const next={...f,objects:f.objects.map((r,i)=>i===0?{...r,id:'replacement'}:r)};
 const pending=layer.prepare(next,'synthetic-origin',true,null,[],null,null);
 expect(layer.inspect(1).rows[0].id).toBe(f.objects[0].id);
 await pending;const after=layer.stats().assignments;
 expect(after[0].id).toBe('replacement');expect(after[0].slot).toBe(before[0].slot);
 expect(after.slice(1)).toEqual(before.slice(1));expect(new Set(after.map(r=>r.slot)).size).toBe(5000);
 layer.dispose();
});
