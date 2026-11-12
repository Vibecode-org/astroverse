import * as THREE from 'three';
import { physicalFrame, physicalFrameAsync, yieldPhysicalWork, renderPosition, relativeToReference } from './coordinates.js';

export const LOD_LIMITS = Object.freeze({ objects:4096, detailed:32, scan:128, enter:20, exit:28 });
// Both levels are screen markers, never measured radii. One logical ID/slot.
export function createPhysicalLayer(scene) {
  let capacity=8, geometry, positions, colors, levels;
  const material=new THREE.ShaderMaterial({ vertexColors:true, uniforms:{markerPixelRatio:{value:1},renderShift:{value:new THREE.Vector3()}},
    vertexShader:`#include <common>
      #include <logdepthbuf_pars_vertex>
      uniform vec3 renderShift; uniform float markerPixelRatio; attribute float level; varying vec3 tint; varying float detail;
      void main(){tint=color;detail=level;gl_Position=projectionMatrix*modelViewMatrix*vec4(position-renderShift,1.);
      #include <logdepthbuf_vertex>
      gl_PointSize=level<0.?0.:(level>.5?15.:5.)*markerPixelRatio;}`,
    fragmentShader:`#include <logdepthbuf_pars_fragment>
      varying vec3 tint; varying float detail;
      void main(){
      #include <logdepthbuf_fragment>
      float r=length(gl_PointCoord-vec2(.5));
      if(detail<0. || r>.5 || (detail>.5 && r>.18 && r<.34))discard;
      gl_FragColor=vec4(tint,1.);}` });
  const points=new THREE.Points(undefined,material); points.frustumCulled=false;
  const allocate=()=>{
    const old=geometry;
    geometry=new THREE.BufferGeometry();
    const p=new Float32Array(capacity*3),c=new Float32Array(capacity*3),l=new Float32Array(capacity).fill(-1);
    if(positions){p.set(positions);c.set(colors);l.set(levels);}
    positions=p;colors=c;levels=l;
    geometry.setAttribute('position',new THREE.BufferAttribute(p,3));
    geometry.setAttribute('color',new THREE.BufferAttribute(c,3));
    geometry.setAttribute('level',new THREE.BufferAttribute(l,1));
    geometry.setDrawRange(0,0);points.geometry=geometry;old?.dispose();
  };
  allocate();scene.add(points);
  let preparation=0, pickGroups=null;
  let rows=[],origin=[0,0,0],hierarchy=null,selected=null,cursor=0;
  let slots=new Map();
  const details=new Set(), vector=new THREE.Vector3();
  const metrics={applyMs:0,maxApplyMs:0,lodMs:0,maxLodMs:0,visited:0,pickMs:0,prepareMs:0,sliceMaxMs:0};
  let levelDirty=false;
  const level=(id,value)=>{levels[slots.get(id)]=value;levelDirty=true;if(value)details.add(id);else details.delete(id);};
  const api = {
    update(frame,centerId,overview=false,neighborhood=null,bodies=[],selectedId=null,reference=null){
      preparation++;pickGroups=null;
      material.uniforms.renderShift.value.set(0,0,0);
      const start=performance.now();
      // Explicit eviction must not synchronously delete 100k Map entries.
      if(!frame){
        rows=[];hierarchy=null;selected=null;cursor=0;slots=new Map();details.clear();
        levels.fill(-1);geometry.attributes.level.needsUpdate=true;
        geometry.setDrawRange(0,0);points.visible=false;
        metrics.applyMs=performance.now()-start;metrics.maxApplyMs=Math.max(metrics.maxApplyMs,metrics.applyMs);
        return;
      }
      const parsed=frame?physicalFrame(frame):{rows:[],hierarchy:null};
      if(parsed.rows.length>(frame?.synthetic === true && frame?.profile === 'synthetic-s100k' ? 100000 : LOD_LIMITS.objects))throw new Error('Слишком много центров в positions/1');
      const ids=new Set(parsed.rows.map(row=>row.id));
      if(ids.size!==parsed.rows.length)throw new Error('Повтор центра');
      hierarchy=parsed.hierarchy;rows=parsed.rows;selected=selectedId;
      if(reference)origin=reference.position.map((v,a)=>v+reference.offset[a]);
      else if(frame)origin=rows.find(row=>row.id===centerId)?.position||origin;
      const relative=row=>reference?relativeToReference(row,hierarchy,reference):hierarchy?.relative(row.id,centerId)||row.position.map((v,a)=>v-origin[a]);
      // The manager selects resident sectors. Submit every known center in
      // that frame; a camera-distance cutoff would hide distant visible bodies.
      const live=new Set(rows.map(row=>row.id));
      for(const [id,slot] of slots)if(!live.has(id)){slots.delete(id);details.delete(id);levels[slot]=-1;}
      if(rows.length>capacity){while(capacity<rows.length)capacity*=2;allocate();}
      const used=new Set(slots.values());let free=0;
      const palette=new Map(bodies.map(body=>[body.id,body.color]));
      for(const row of rows){
        if(!slots.has(row.id)){while(used.has(free))free++;slots.set(row.id,free);used.add(free);levels[free]=0;}
        const slot=slots.get(row.id);
        positions.set(renderPosition(relative(row),[0,0,0]),slot*3);
        const color=new THREE.Color(palette.get(row.id)||'#ffffff');colors.set([color.r,color.g,color.b],slot*3);
      }
      for(const attr of Object.values(geometry.attributes))attr.needsUpdate=true;
      geometry.setDrawRange(0,slots.size?Array.from(slots.values()).reduce((a,b)=>Math.max(a,b),-1)+1:0);points.visible=rows.length>0;
      cursor=rows.length?cursor%rows.length:0;metrics.applyMs=performance.now()-start;metrics.maxApplyMs=Math.max(metrics.maxApplyMs,metrics.applyMs);
    },
    async prepare(frame,centerId,overview,neighborhood,bodies,selectedId,reference){
      const token=++preparation, started=performance.now();
      const liveReference=reference;
      if(reference)reference={...reference,position:[...reference.position],offset:[...reference.offset]};
      metrics.sliceMaxMs=0;
      const slice=ms=>{metrics.sliceMaxMs=Math.max(metrics.sliceMaxMs,ms);api.onPhase?.({kind:"preparation_slice_cpu",ms});};
      const check=()=>{if(token!==preparation)throw new DOMException('cancelled','AbortError');};
      let parsed;
      try { parsed=await physicalFrameAsync(frame,check,slice,centerId); }
      catch(error){if(error.name==='AbortError')return false;throw error;}
      if(token!==preparation)return false;
      if(frame.synthetic!==true || frame.profile!=='synthetic-s100k' || parsed.rows.length>100000)
        throw new Error('Invalid large physical frame');
      const nextOrigin=reference?reference.position.map((v,a)=>v+reference.offset[a]):(centerId==='synthetic-origin'?[0,0,0]:parsed.centerPosition||(parsed.rows.length<=4096?parsed.rows.find(r=>r.id===centerId)?.position:null)||origin);
      const nextRows=parsed.rows, nextSlots=new Map(), seen=new Set(), groups=new Map();
      let nextCapacity=8;while(nextCapacity<parsed.rows.length)nextCapacity*=2;
      const p=new Float32Array(nextCapacity*3), c=new Float32Array(nextCapacity*3), l=new Float32Array(nextCapacity).fill(-1);
      const palette=new Map(bodies.map(body=>[body.id,body.color])), color=new THREE.Color();
      // Stable slots for surviving IDs, reuse holes without a scene rebuild.
      const used=new Uint8Array(nextCapacity);
      if(slots.size)for(let offset=0;offset<parsed.rows.length;offset+=256){
        await yieldPhysicalWork();if(token!==preparation)return false;
        const start=performance.now();
        for(let i=offset;i<Math.min(offset+256,parsed.rows.length);i++){
          const id=parsed.rows[i].id,slot=slots.get(id);
          if(slot!==undefined&&slot<nextCapacity){nextSlots.set(id,slot);used[slot]=1;}
        }
        slice(performance.now()-start);
      }
      let free=0, high=0;
      for(let offset=0;offset<parsed.rows.length;offset+=256){
        await yieldPhysicalWork();
        if(token!==preparation)return false;
        const start=performance.now();
        for(let i=offset;i<Math.min(offset+256,parsed.rows.length);i++){
          const row=parsed.rows[i];
          if(seen.has(row.id))throw new Error('Повтор центра');seen.add(row.id);

          if(!nextSlots.has(row.id)){while(used[free])free++;nextSlots.set(row.id,free);used[free]=1;}
          const slot=nextSlots.get(row.id);high=Math.max(high,slot+1);
          if(parsed.hierarchy){
            const relative=reference?relativeToReference(row,parsed.hierarchy,reference):parsed.hierarchy.relative(row.id,centerId);
            p.set(renderPosition(relative,[0,0,0]),slot*3);
          }else{
            // Avoid three temporary arrays per stationary flat center.
            p[slot*3]=(row.position[0]-(reference?reference.position[0]:nextOrigin[0])-(reference?reference.offset[0]:0))/100000;
            p[slot*3+1]=(row.position[2]-(reference?reference.position[2]:nextOrigin[2])-(reference?reference.offset[2]:0))/100000;
            p[slot*3+2]=-(row.position[1]-(reference?reference.position[1]:nextOrigin[1])-(reference?reference.offset[1]:0))/100000;
          }
          color.set(palette.get(row.id)||'#66bbff');c[slot*3]=color.r;c[slot*3+1]=color.g;c[slot*3+2]=color.b;l[slot]=0;
          const bucket=slot>>>8;
          if(!groups.has(bucket))groups.set(bucket,{box:new THREE.Box3(),rows:[]});
          const group=groups.get(bucket);group.box.expandByPoint(vector.fromArray(p,slot*3));group.rows.push(row);
        }
        slice(performance.now()-start);
      }
      if(token!==preparation)return false;
      const commitStart=performance.now();
      if(nextCapacity>capacity){capacity=nextCapacity;allocate();}
      const committedOrigin=liveReference?liveReference.position.map((v,a)=>v+liveReference.offset[a]):nextOrigin;
      material.uniforms.renderShift.value.fromArray(renderPosition(committedOrigin,nextOrigin));
      positions.fill(0);positions.set(p);colors.set(c);levels.fill(-1);levels.set(l);
      slots=nextSlots;
      pickGroups=[...groups.values()];rows=nextRows;origin=committedOrigin;hierarchy=parsed.hierarchy;selected=selectedId;details.clear();cursor=0;
      for(const attr of Object.values(geometry.attributes))attr.needsUpdate=true;
      geometry.setDrawRange(0,high);points.visible=rows.length>0;
      metrics.applyMs=performance.now()-commitStart;metrics.maxApplyMs=Math.max(metrics.maxApplyMs,metrics.applyMs);
      metrics.prepareMs=performance.now()-started;return true;
    },
    rebase(deltaKm){
      const delta=renderPosition(deltaKm,[0,0,0]);
      material.uniforms.renderShift.value.add(new THREE.Vector3(...delta));
      origin=origin.map((v,a)=>v+deltaKm[a]);
    },
    tick(camera,pixelRatio=1){
      material.uniforms.markerPixelRatio.value=pixelRatio;
      const start=performance.now();let visited=0;
      if(slots.has(selected)&&!details.has(selected)){
        if(details.size>=LOD_LIMITS.detailed)level(details.values().next().value,0);
        level(selected,1);
      }
      for(let n=0;n<Math.min(rows.length,LOD_LIMITS.scan);n++){
        const row=rows[cursor%rows.length];cursor=(cursor+1)%rows.length;visited++;
        const slot=slots.get(row.id);vector.fromArray(positions,slot*3).sub(material.uniforms.renderShift.value);
        const distance=vector.distanceTo(camera.position);
        if(row.id!==selected){
          if(details.has(row.id)&&distance>=LOD_LIMITS.exit)level(row.id,0);
          else if(!details.has(row.id)&&distance<=LOD_LIMITS.enter&&details.size<LOD_LIMITS.detailed)level(row.id,1);
        }
      }
      if(levelDirty){geometry.attributes.level.needsUpdate=true;levelDirty=false;}
      metrics.visited=visited;metrics.lodMs=performance.now()-start;metrics.maxLodMs=Math.max(metrics.maxLodMs,metrics.lodMs);
    },
    pick(camera,x,y,width,height){
      const started=performance.now();camera.updateMatrixWorld();let result=null,best=Infinity,bestDepth=Infinity;
      const view=camera.matrixWorldInverse.elements;
      let candidates=rows;
      if(pickGroups){
        const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2(x/width*2-1,1-y/height*2),camera);
        const box=new THREE.Box3(),center=new THREE.Vector3(),size=new THREE.Vector3();
        candidates=[];
        for(const group of pickGroups){
          group.box.getCenter(center);group.box.getSize(size);
          const far=center.sub(material.uniforms.renderShift.value).distanceTo(camera.position)+size.length();
          const margin=far*2*Math.tan(camera.fov*Math.PI/360)*10/height;
          box.copy(group.box).translate(material.uniforms.renderShift.value.clone().negate()).expandByScalar(margin);
          if(ray.ray.intersectsBox(box))candidates.push(...group.rows);
        }
      }
      for(const row of candidates){
        const slot=slots.get(row.id);vector.fromArray(positions,slot*3).sub(material.uniforms.renderShift.value);
        const depth=-(view[2]*vector.x+view[6]*vector.y+view[10]*vector.z+view[14]);vector.project(camera);
        if(vector.z < -1||vector.z>1)continue;
        const distance=Math.hypot((vector.x+1)*width/2-x,(1-vector.y)*height/2-y);
        if(distance<= (details.has(row.id)?9:6)
          && (distance<best-1e-6 || Math.abs(distance-best)<=1e-6&&(depth<bestDepth || depth===bestDepth && row.id<result))){
          best=distance;bestDepth=depth;result=row.id;
        }
      }
      metrics.pickMs=performance.now()-started;return result;
    },
    timing:()=>({...metrics,slots:slots.size,capacity,bufferBytes:capacity*28,detailed:details.size}),
    stats:()=>({...metrics,capacity,bufferBytes:capacity*28,slots:slots.size,detailed:details.size,
      assignments:rows.map(row=>({id:row.id,slot:slots.get(row.id),level:details.has(row.id)?1:0}))}),
    cameraChart:id=>({position:[...(rows.find(row=>row.id===id)?.position||origin)],
      path:hierarchy?.path(id)||null,offset:[0,0,0]}),
    inspect:(limit=rows.length)=>({origin:[...origin],rows:rows.slice(0,limit).map(row=>({id:row.id,position:[...row.position]})),
      render:rows.slice(0,limit).flatMap(row=>Array.from(positions.slice(slots.get(row.id)*3,slots.get(row.id)*3+3),(v,a)=>v-material.uniforms.renderShift.value.getComponent(a))),
      hierarchy:hierarchy?{binding:hierarchy.binding,addresses:rows.slice(0,limit).map(row=>hierarchy.address(row.id))}:null}),
    dispose(){preparation++;pickGroups=null;scene.remove(points);geometry.dispose();material.dispose();rows=[];slots.clear();details.clear();hierarchy=null;},
  };
  return api;
}
