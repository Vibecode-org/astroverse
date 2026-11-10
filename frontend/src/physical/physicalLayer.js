import * as THREE from 'three';
import { physicalFrame, renderPosition } from './coordinates.js';

export const LOD_LIMITS = Object.freeze({ objects:4096, detailed:32, scan:128, enter:20, exit:28 });
// Both levels are screen markers, never measured radii. One logical ID/slot.
export function createPhysicalLayer(scene) {
  let capacity=8, geometry, positions, colors, levels;
  const material=new THREE.ShaderMaterial({ vertexColors:true, uniforms:{markerPixelRatio:{value:1}},
    vertexShader:`uniform float markerPixelRatio; attribute float level; varying vec3 tint; varying float detail;
      void main(){tint=color;detail=level;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);
      gl_PointSize=level<0.?0.:(level>.5?15.:5.)*markerPixelRatio;}`,
    fragmentShader:`varying vec3 tint; varying float detail;
      void main(){float r=length(gl_PointCoord-vec2(.5));
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
  let rows=[],origin=[0,0,0],hierarchy=null,selected=null,cursor=0;
  const slots=new Map(), details=new Set(), vector=new THREE.Vector3();
  const metrics={applyMs:0,maxApplyMs:0,lodMs:0,maxLodMs:0,visited:0};
  const level=(id,value)=>{levels[slots.get(id)]=value;if(value)details.add(id);else details.delete(id);};
  return {
    update(frame,centerId,overview=false,neighborhood=null,bodies=[],selectedId=null){
      const start=performance.now();
      const parsed=frame?physicalFrame(frame):{rows:[],hierarchy:null};
      if(parsed.rows.length>LOD_LIMITS.objects)throw new Error('Слишком много центров в positions/1');
      const ids=new Set(parsed.rows.map(row=>row.id));
      if(ids.size!==parsed.rows.length)throw new Error('Повтор центра');
      hierarchy=parsed.hierarchy;rows=parsed.rows;selected=selectedId;
      if(frame)origin=rows.find(row=>row.id===centerId)?.position||origin;
      const relative=row=>hierarchy?.relative(row.id,centerId)||row.position.map((v,a)=>v-origin[a]);
      if(!overview)rows=rows.filter(row=>Math.hypot(...relative(row).map((v,a)=>v-(neighborhood?.offset[a]||0)))<=(neighborhood?.radius??2e6));
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
      geometry.setDrawRange(0,slots.size?Math.max(...slots.values())+1:0);points.visible=rows.length>0;
      cursor=rows.length?cursor%rows.length:0;metrics.applyMs=performance.now()-start;metrics.maxApplyMs=Math.max(metrics.maxApplyMs,metrics.applyMs);
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
        const slot=slots.get(row.id);vector.fromArray(positions,slot*3);
        const distance=vector.distanceTo(camera.position);
        if(row.id!==selected){
          if(details.has(row.id)&&distance>=LOD_LIMITS.exit)level(row.id,0);
          else if(!details.has(row.id)&&distance<=LOD_LIMITS.enter&&details.size<LOD_LIMITS.detailed)level(row.id,1);
        }
      }
      geometry.attributes.level.needsUpdate=true;
      metrics.visited=visited;metrics.lodMs=performance.now()-start;metrics.maxLodMs=Math.max(metrics.maxLodMs,metrics.lodMs);
    },
    pick(camera,x,y,width,height){
      camera.updateMatrixWorld();let result=null,best=Infinity;
      for(const row of rows){
        const slot=slots.get(row.id);vector.fromArray(positions,slot*3).project(camera);
        if(vector.z < -1||vector.z>1)continue;
        const distance=Math.hypot((vector.x+1)*width/2-x,(1-vector.y)*height/2-y);
        if(distance<= (details.has(row.id)?9:6)&&distance<best){best=distance;result=row.id;}
      }
      return result;
    },
    stats:()=>({...metrics,capacity,bufferBytes:capacity*28,slots:slots.size,detailed:details.size,
      assignments:rows.map(row=>({id:row.id,slot:slots.get(row.id),level:details.has(row.id)?1:0}))}),
    inspect:()=>({origin:[...origin],rows:rows.map(row=>({id:row.id,position:[...row.position]})),
      render:rows.flatMap(row=>Array.from(positions.slice(slots.get(row.id)*3,slots.get(row.id)*3+3))),
      hierarchy:hierarchy?{binding:hierarchy.binding,addresses:rows.map(row=>hierarchy.address(row.id))}:null}),
    dispose(){scene.remove(points);geometry.dispose();material.dispose();rows=[];slots.clear();details.clear();hierarchy=null;},
  };
}
