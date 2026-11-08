/** Node --expose-gc tests/benchmark_hierarchy.mjs; synthetic charts only.
 * Heap deltas describe retained graph allocations above an already loaded frame,
 * not browser RSS, GPU memory or absolute astronomical accuracy.
 */
import fs from 'node:fs';
import { PhysicalHierarchy } from '../frontend/src/physical/hierarchy.js';
if (!global.gc) throw new Error('Run node --expose-gc tests/benchmark_hierarchy.mjs');
const fixture=JSON.parse(fs.readFileSync(new URL('./fixtures/physical_hierarchy_synthetic.json',import.meta.url)));
const large=structuredClone(fixture.frame),h=large.hierarchy;
h.sectors=Array.from({length:128},(_,i)=>({id:`sector-${i}`,origin_km:[0,0,0]}));
h.systems=Array.from({length:512},(_,i)=>({id:`system-${i}`,sector_id:`sector-${i%128}`,offset_km:[0,0,0]}));
large.objects=Array.from({length:4096},(_,i)=>({id:`synthetic-${i}`,status:'computed',position:[i,2*i,3*i]}));
h.bodies=large.objects.map((row,i)=>({id:row.id,system_id:`system-${i%512}`,offset_km:[...row.position]}));
const measure=(frame,iterations)=>{
  for(let i=0;i<10;i++)new PhysicalHierarchy(frame);
  global.gc();const before=process.memoryUsage().heapUsed;
  const batch=frame.objects.length<100?500:3;
  const graphs=Array.from({length:batch},()=>new PhysicalHierarchy(frame));
  global.gc();const retained=(process.memoryUsage().heapUsed-before)/batch;
  const times=[];
  for(let i=0;i<iterations;i++){
    const start=performance.now();const sample=new PhysicalHierarchy(frame);
    sample.relative(frame.objects[1].id,frame.objects[0].id);
    times.push(performance.now()-start);
  }
  times.sort((a,b)=>a-b);
  return {bodies:frame.objects.length,iterations,median_ms:times[Math.floor(times.length/2)],
    retained_batch_graphs:batch,retained_heap_bytes_per_graph:retained,known_center:graphs[0].absolute(frame.objects[0].id)};
};
console.log(JSON.stringify({small:measure(fixture.frame,1000),bounded_max:measure(large,50)},null,2));
