// Offline numerical footprint accounting for the declared initial camera.
// Does not control the browser, load the manager or measure GPU occlusion.
import * as THREE from '../frontend/node_modules/three/build/three.module.js';
const camera=new THREE.PerspectiveCamera(50,1920/1080,.00001,1e12);
camera.position.set(0,8,24);camera.lookAt(0,0,0);camera.updateMatrixWorld();
const grid=new Map(),marked=new Uint8Array(100000),v=new THREE.Vector3();let pairs=0;
for(let n=0;n<100000;n++){
 const k=n===50001?50000:n;
 v.set(Math.fround((k%400-199.5)*.04),Math.fround((Math.floor(k/400)-124.5)*.04),0).project(camera);
 const x=(v.x+1)*960,y=(1-v.y)*540,cx=Math.floor(x/5),cy=Math.floor(y/5);
 for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)for(const p of grid.get(`${cx+dx},${cy+dy}`)||[]){
  if((p.x-x)**2+(p.y-y)**2<=25){pairs++;marked[n]=marked[p.n]=1;}
 }
 const key=`${cx},${cy}`;if(!grid.has(key))grid.set(key,[]);grid.get(key).push({x,y,n});
}
console.log(JSON.stringify({objects:100000,nominal_disk_diameter_css_px:5,objects_with_overlapping_footprints:marked.reduce((a,b)=>a+b,0),overlapping_pairs:pairs,
 scope:'Offline projected Float32 centers, initial declared camera/1080p/DPR1; nominal circular footprints, not measured raster occlusion.'}));
