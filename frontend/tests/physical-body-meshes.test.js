import { it, expect, vi } from 'vitest';
import * as THREE from 'three';
import { createBodyMeshes } from '../src/physical/bodyMeshes.js';
import { getBodyModel } from '../src/physical/bodyModel.js';
const rows=[{id:'earth',position:[0,0,0]},{id:'sun',position:[1e8,0,0]}];
const frame={jd_tdb:2451545};
const assets={earth:{url:'/test-earth.png'},sun:{url:'/test-sun.png'}};
const relative=row=>row.id==='earth'?[0,0,0]:[1000,0,0];
function camera(radiusPx){const c=new THREE.PerspectiveCamera(50,1,.00001,1e8);c.position.z=getBodyModel('earth').radiusKm/100000*600/(2*Math.tan(c.fov*Math.PI/360)*radiusPx);c.lookAt(0,0,0);return c;}
it('admits physical spheres by projected size with hysteresis, deterministic centers, and bounded lazy resources',()=>{
 const scene=new THREE.Scene(),layer=createBodyMeshes(scene,{assets,loader:{load:()=>new THREE.Texture()}});
 layer.update(frame,rows,relative);expect(layer.inspect().resources).toEqual({geometries:0,materials:0,textures:0});
 layer.tick(camera(7));expect(layer.visible('earth')).toBe(false);
 layer.tick(camera(9));expect(layer.visible('earth')).toBe(true);
 layer.tick(camera(6));expect(layer.visible('earth')).toBe(true);
 layer.tick(camera(4));expect(layer.visible('earth')).toBe(false);
 const body=layer.inspect().bodies.find(b=>b.id==='earth');expect(body.center).toEqual([0,0,0]);expect(body.sunDirection).toEqual([1,0,-0]);
 expect(layer.inspect().resources.geometries).toBe(1);expect(layer.inspect().meshes).toBeLessThanOrEqual(5);
 layer.update({...frame,synthetic:true},rows,relative);expect(layer.inspect().meshes).toBe(0);layer.dispose();expect(scene.children).toHaveLength(0);
});
it('picks measured sphere surfaces away from centers, rebases linearly and hides stale frames',()=>{
 const layer=createBodyMeshes(new THREE.Scene(),{assets,loader:{load:()=>new THREE.Texture()}}),c=camera(80);
 layer.update(frame,rows,relative);layer.tick(c,600,'earth');
 expect(layer.pick(c,340,300,600,600)?.id).toBe('earth');
 layer.rebase(new THREE.Vector3(1,2,3));expect(layer.inspect().bodies.find(b=>b.id==='earth').center).toEqual([-1,-2,-3]);
 layer.update(null,[],relative);expect(layer.pick(c,300,300,600,600)).toBe(null);expect(layer.inspect().visible).toEqual([]);layer.dispose();
});
it('keeps failed textures safe and disposes pending loads without resurrection',()=>{
 let done,failed;const texture=new THREE.Texture(),dispose=vi.spyOn(texture,'dispose');
 const scene=new THREE.Scene(),layer=createBodyMeshes(scene,{assets,loader:{load:(url,onLoad,p,onError)=>{done=onLoad;failed=onError;return texture;}}});
 layer.update(frame,rows,relative);layer.tick(camera(80));failed();expect(layer.inspect().bodies.find(b=>b.id==='earth').texture).toBe('failed');
 layer.dispose();done(texture);expect(dispose).toHaveBeenCalled();expect(scene.children).toHaveLength(0);
});
it('removes unsupported orientation meshes without keeping their previous frame',()=>{
 const scene=new THREE.Scene(),layer=createBodyMeshes(scene);
 layer.update(frame,rows,relative);layer.tick(camera(80));expect(layer.visible('earth')).toBe(true);
 layer.update({jd_tdb:2462503},rows,relative);expect(layer.inspect().bodies).toEqual([]);expect(layer.visible('earth')).toBe(false);
 layer.dispose();expect(scene.children).toHaveLength(0);
});
it('uses neutral offline spheres by default and releases a successfully loaded injected map',()=>{
 const offline=createBodyMeshes(new THREE.Scene());offline.update(frame,rows,relative);offline.tick(camera(80));
 expect(offline.inspect().resources.textures).toBe(0);expect(offline.inspect().bodies.find(b=>b.id==='earth').texture).toBe('missing');offline.dispose();
 let done;const texture=new THREE.Texture(),dispose=vi.spyOn(texture,'dispose');
 const layer=createBodyMeshes(new THREE.Scene(),{assets,loader:{load:(url,onLoad)=>{done=onLoad;return texture;}}});
 layer.update(frame,rows,relative);layer.tick(camera(80));done(texture);
 expect(texture.colorSpace).toBe(THREE.SRGBColorSpace);expect(layer.inspect().bodies.find(b=>b.id==='earth').texture).toBe('loaded');
 layer.update(null,[],relative);expect(dispose).toHaveBeenCalledTimes(1);layer.dispose();
});
