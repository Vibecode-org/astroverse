import * as THREE from 'three';
import { getBodyModel, bodyOrientation, sunlightDirection } from './bodyModel.js';
import { BODY_ASSETS } from './bodyAssets.js';
import { KM_PER_RENDER_UNIT } from './coordinates.js';

export const BODY_LOD = Object.freeze({ enterRadiusPx:8, exitRadiusPx:5, meshes:5 });
// Scene-owned resources. Never use the legacy catalog's mutable/global caches.
export function createBodyMeshes(scene, {loader = new THREE.TextureLoader(), assets = BODY_ASSETS} = {}) {
  const entries=new Map();let geometry=null,disposed=false,selection=null;
  const raycaster=new THREE.Raycaster(),hit=new THREE.Vector3(),frustum=new THREE.Frustum(),projection=new THREE.Matrix4();
  function remove(id) {
    const entry=entries.get(id);if(!entry)return;
    scene.remove(entry.mesh);entry.texture?.dispose();entry.material?.dispose();entries.delete(id);
  }
  function admit(entry) {
    const {id}=entry;

    const material=new THREE.ShaderMaterial({
      uniforms:{surface:{value:null},hasMap:{value:false},tint:{value:new THREE.Color(assets[id]?.color || '#aaaaaa')},sunDirection:{value:new THREE.Vector3()},emissive:{value:id==='sun'},lit:{value:false}},
      vertexShader:`#include <common>
      #include <logdepthbuf_pars_vertex>
      varying vec2 texcoord; varying vec3 worldNormal;
      void main(){texcoord=uv;worldNormal=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);
      #include <logdepthbuf_vertex>
      }`,
      fragmentShader:`#include <logdepthbuf_pars_fragment>
      uniform sampler2D surface;uniform bool hasMap;uniform vec3 tint;uniform vec3 sunDirection;uniform bool emissive;uniform bool lit;varying vec2 texcoord;varying vec3 worldNormal;
      void main(){
      #include <logdepthbuf_fragment>
      vec3 albedo=hasMap?texture2D(surface,texcoord).rgb:tint;
      float illumination=emissive?1.:(lit?max(0.,dot(normalize(worldNormal),sunDirection)):0.);
      gl_FragColor=vec4(albedo*illumination,1.);
      #include <tonemapping_fragment>
      #include <colorspace_fragment>
      }`});
    entry.material=material;
    material.uniforms.lit.value=!!entry.light;
    if(entry.light)material.uniforms.sunDirection.value.fromArray(entry.light);
    const asset=assets[id];
    if(asset?.url){
      entry.textureState='loading';
      try { entry.texture=loader.load(asset.url,texture=>{
        if(disposed || entries.get(id)!==entry){texture.dispose();return;}
        texture.colorSpace=THREE.SRGBColorSpace;texture.wrapS=THREE.RepeatWrapping;
        entry.texture=texture;material.uniforms.surface.value=texture;material.uniforms.hasMap.value=true;entry.textureState='loaded';
      },undefined,()=>{if(entries.get(id)===entry)entry.textureState='failed';}); }
      catch {entry.textureState='failed';}
    }

  }
  return {
    update(frame,rows,relative) {
      if(selection)selection.visible=false;
      const live=new Set();const sun=rows.find(row=>row.id==='sun');
      if(frame?.synthetic!==true)for(const row of rows){
        const model=getBodyModel(row.id),orientation=bodyOrientation(row.id,frame.jd_tdb);
        if(!model || !orientation)continue;live.add(row.id);
        let entry=entries.get(row.id);
        if(!entry){
          const mesh=new THREE.Object3D();mesh.visible=false;mesh.name=`physical-body:${row.id}`;mesh.scale.setScalar(model.radiusKm/KM_PER_RENDER_UNIT);
          entry={id:row.id,model,mesh,material:null,texture:null,textureState:'missing',radiusPx:0,light:null};entries.set(row.id,entry);
        }
        entry.mesh.position.fromArray(relative(row));entry.mesh.quaternion.copy(orientation);
        const direction=sun?sunlightDirection(row.position,sun.position):null;
        entry.light=direction?.toArray()||null;if(entry.material)entry.material.uniforms.lit.value=!!direction;
        if(direction && entry.material)entry.material.uniforms.sunDirection.value.copy(direction);
      }
      for(const id of entries.keys())if(!live.has(id))remove(id);
    },
    tick(camera,height=600,selected=null,pixelRatio=1){
      if(selection)selection.visible=false;
      camera.updateMatrixWorld();const view=new THREE.Vector3();
      frustum.setFromProjectionMatrix(projection.multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse));
      for(const entry of entries.values()){
        view.copy(entry.mesh.position).applyMatrix4(camera.matrixWorldInverse);
        const radius=entry.model.radiusKm/KM_PER_RENDER_UNIT;
        const distance=entry.mesh.position.distanceTo(camera.position);
        entry.radiusPx=distance<=radius?Infinity:radius*height/(2*Math.tan(camera.fov*Math.PI/360)*Math.max(1e-12,-view.z));
        const visible=frustum.intersectsSphere(new THREE.Sphere(entry.mesh.position,radius)) && (view.z<radius || distance<=radius) && entry.radiusPx>=(entry.mesh.visible?BODY_LOD.exitRadiusPx:BODY_LOD.enterRadiusPx);
        if(visible && !entry.mesh.isMesh){
          admit(entry);
          geometry ||= new THREE.SphereGeometry(1,64,32);
          const mesh=new THREE.Mesh(geometry,entry.material);mesh.copy(entry.mesh);entry.mesh=mesh;scene.add(mesh);
        }
        entry.mesh.visible=visible;
        if(visible && entry.id===selected){
          if(!selection){
            const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute([0,0,0],3));
            const m=new THREE.ShaderMaterial({depthTest:false,depthWrite:false,transparent:true,uniforms:{size:{value:20}},vertexShader:'uniform float size; void main(){gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);gl_PointSize=size;}',fragmentShader:'void main(){float r=length(gl_PointCoord-vec2(.5));if(r>.49||r<.46)discard;gl_FragColor=vec4(1.,.8,.2,1.);}'});
            selection=new THREE.Points(g,m);selection.frustumCulled=false;selection.renderOrder=10;selection.name='physical-selection';scene.add(selection);
          }
          selection.position.copy(entry.mesh.position);selection.visible=distance>radius;
          selection.material.uniforms.size.value=Math.min(2048,Math.max(20,entry.radiusPx*2+10))*pixelRatio;
        }
      }
    },
    rebase(delta){for(const entry of entries.values())entry.mesh.position.sub(delta);},
    ids:()=>entries.keys(),
    visible:id=>entries.get(id)?.mesh.visible===true,
    pick(camera,x,y,width,height){
      raycaster.setFromCamera(new THREE.Vector2(x/width*2-1,1-y/height*2),camera);let best=null;
      for(const entry of entries.values())if(entry.mesh.visible){
        const sphere=new THREE.Sphere(entry.mesh.position,entry.model.radiusKm/KM_PER_RENDER_UNIT);
        if(!sphere.containsPoint(camera.position) && raycaster.ray.intersectSphere(sphere,hit)){
          const distance=hit.distanceTo(raycaster.ray.origin);
          if(distance>=camera.near && distance<=camera.far && (!best||distance<best.distance))best={id:entry.id,distance};
        }
      }
      return best;
    },
    inspect:()=>({meshes:[...entries.values()].filter(e=>e.mesh.isMesh).length,visible:[...entries.values()].filter(e=>e.mesh.visible).map(e=>e.id),resources:{geometries:(geometry?1:0)+(selection?1:0),materials:[...entries.values()].filter(e=>e.material).length+(selection?1:0),textures:[...entries.values()].filter(e=>e.texture).length},bodies:[...entries.values()].map(e=>({id:e.id,radiusKm:e.model.radiusKm,center:e.mesh.position.toArray(),quaternion:e.mesh.quaternion.toArray(),sunDirection:e.light,radiusPx:e.radiusPx,visible:e.mesh.visible,texture:e.textureState}))}),
    dispose(){if(selection){scene.remove(selection);selection.geometry.dispose();selection.material.dispose();}disposed=true;for(const id of entries.keys())remove(id);geometry?.dispose();geometry=null;},
  };
}
