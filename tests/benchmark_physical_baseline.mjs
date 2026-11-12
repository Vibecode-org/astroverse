import * as THREE from '../frontend/node_modules/three/build/three.module.js';
import {createPhysicalLayer} from '../frontend/src/physical/physicalLayer.js';
const scene=new THREE.Scene(), layer=createPhysicalLayer(scene),camera=new THREE.PerspectiveCamera(50,16/9,.00001,1e12);camera.position.set(0,8,12);camera.lookAt(0,0,0);camera.updateMatrixWorld();
const frame={version:'positions/1',jd_tdb:2451545,coordinates:{representation:'simulation_position',unit:'km',reference_system:'ICRF',origin:'solar_system_barycenter',time_scale:'TDB',corrections:'NONE'},objects:Array.from({length:4096},(_,i)=>({id:`s-${i}`,status:'computed',position:[(i%64-32)*1000,0,(Math.floor(i/64)-32)*1000]}))};
const apply=[],lod=[],pick=[];
for(let n=0;n<40;n++){let t=performance.now();layer.update(frame,'s-0',true);apply.push(performance.now()-t);t=performance.now();layer.tick(camera);lod.push(performance.now()-t);t=performance.now();layer.pick(camera,960,540,1920,1080);pick.push(performance.now()-t);}
const dist=a=>{a=a.slice(5).sort((a,b)=>a-b);return {n:a.length,p95:a[Math.ceil(a.length*.95)-1],max:a.at(-1)}};
console.log(JSON.stringify({environment:process.version,objects:4096,apply:dist(apply),lod:dist(lod),pick:dist(pick),stats:layer.stats().bufferBytes}));layer.dispose();
