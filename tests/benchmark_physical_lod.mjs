// Component retained memory above preloaded synthetic input; no HTTP collector.
import * as THREE from '../frontend/node_modules/three/build/three.module.js';
import { createPhysicalLayer } from '../frontend/src/physical/physicalLayer.js';
if(!global.gc)throw Error('use --expose-gc');
const frame={version:'positions/1',jd_tdb:2451545,coordinates:{representation:'simulation_position',unit:'km',reference_system:'ICRF',origin:'solar_system_barycenter',time_scale:'TDB',corrections:'NONE'},objects:Array.from({length:4096},(_,i)=>({id:String(i),status:'computed',position:[i*100,0,0]}))};
const camera=new THREE.PerspectiveCamera();camera.position.z=10;
for(let i=0;i<10;i++){const l=createPhysicalLayer(new THREE.Scene());l.update(frame,'0',true);l.tick(camera);l.dispose();}
global.gc();const before=process.memoryUsage();
const layers=Array.from({length:20},()=>{const l=createPhysicalLayer(new THREE.Scene());l.update(frame,'0',true);l.tick(camera);return l;});
global.gc();const after=process.memoryUsage();const apply=[],lod=[],pick=[];
for(let i=0;i<100;i++){const l=layers[0];l.update(frame,'0',true);l.tick(camera);apply.push(l.stats().applyMs);lod.push(l.stats().lodMs);l.pick(camera,720,500,1440,1000);pick.push(l.timing().pickMs);}
const times=a=>{a.sort((a,b)=>a-b);return {n:a.length,median:a[Math.floor(a.length/2)],p95:a[Math.ceil(a.length*.95)-1],max:a.at(-1)};};
console.log(JSON.stringify({objects:4096,batch:20,retained_heap_per_layer:(after.heapUsed-before.heapUsed)/20,retained_arraybuffers_per_layer:(after.arrayBuffers-before.arrayBuffers)/20,client_rss:after.rss,apply_ms:times(apply),lod_ms:times(lod),picking_ms:times(pick),nominal_attributes:layers[0].stats().bufferBytes},null,2));
for(const l of layers)l.dispose();
