/** Native HTTP manager timing and isolated decoded graph allocation in Node/V8.
 * Start the opt-in synthetic Docker provider; node --expose-gc this script.
 * Provider RSS, client RSS and component heap delta are distinct measurements.
 */
import { PhysicalSectorManager, decodedEstimate } from '../frontend/src/physical/sectorManager.js';
import { PhysicalHierarchy } from '../frontend/src/physical/hierarchy.js';
if (!global.gc) throw new Error('Run node --expose-gc');
const base=process.argv[2] || 'http://localhost:5174';
const health=await (await fetch(base+'/api/health')).json();
if (!health.synthetic) throw new Error('Requires isolated synthetic HTTP provider');
await fetch(base+'/api/_test/control',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({delay:350,fail:'',hang:'',mixed:'',conflict:0})});
const providerBefore=await (await fetch(base+'/api/_test/metrics')).json();
const manager=new PhysicalSectorManager({root:base+'/api/positions/v1/'});
let frame;const times=[];
for(let i=0;i<12;i++) {
 const start=performance.now();
 const selection={milliseconds:Date.parse('2020-01-01T00:00:00Z')+i*1000,
   neighborhood:{offset:[0,0,0],radius:1e9},anchor:'synthetic-000',context:'benchmark',retainPrevious:true};
 const [loaded,duplicate]=await Promise.all([manager.load(selection),manager.load(selection)]);
 if(loaded!==duplicate)throw new Error('Identical in-flight HTTP selection was not deduplicated');
 frame=loaded;
 times.push(performance.now()-start);
}
const managerMetrics=manager.inspect();manager.cancel();
if(managerMetrics.requests!==60 || managerMetrics.peakActive!==4)throw new Error('Unexpected HTTP request count/concurrency');
// Preload wire string and warm parser/graph before the component-only delta.
const wire=JSON.stringify(frame);frame=null;
for(let i=0;i<20;i++)new PhysicalHierarchy(JSON.parse(wire));
global.gc();const before=process.memoryUsage();
const graphs=Array.from({length:40},()=>{const frame=JSON.parse(wire);return {frame,hierarchy:new PhysicalHierarchy(frame)};});
global.gc();const after=process.memoryUsage();
const componentHeap=(after.heapUsed-before.heapUsed)/graphs.length;
const bytes=new TextEncoder().encode(wire).length;
const providerAfter=await (await fetch(base+'/api/_test/metrics')).json();
console.log(JSON.stringify({node:process.version,iterations:12,first_ms:times[0],median_ms:[...times].sort((a,b)=>a-b)[6],
 manager:managerMetrics,wire_bytes:bytes,decoded_estimate_bytes:decodedEstimate(bytes)+256*512,
 component_retained_heap_bytes:componentHeap,batch:graphs.length,
 client_rss_before_bytes:before.rss,client_rss_after_bytes:after.rss,
 provider_rss_before_kib:providerBefore.provider_rss_kib,provider_rss_after_kib:providerAfter.provider_rss_kib,
 builder:'none; bounded synthetic fixture generated per request',
 scope:'Heap delta: canonical decoded payload + PhysicalHierarchy/Map copies. Wire string preloaded. RSS: entire separate Node measurement client, not component RSS.'},null,2));
