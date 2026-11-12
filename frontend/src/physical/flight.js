import { Vector3, Quaternion } from 'three';
import { KM_PER_RENDER_UNIT } from './coordinates.js';

const keys = new Set(['KeyW','KeyS','KeyA','KeyD','KeyR','KeyF','KeyQ','KeyE',
  'ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Space','Equal','Minus','NumpadAdd','NumpadSubtract']);
const editable = target => target?.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"])');
const axisX=new Vector3(1,0,0),axisY=new Vector3(0,1,0),axisZ=new Vector3(0,0,1);

/** Real RAF seconds, local camera axes, no simulation-clock dependency/inertia. */
export function createFlight(camera, controls, viewport) {
  let enabled=false, last=null, pointer=null, speed=100000, orbitSleeping=false;
  const held=new Set(), movement=new Vector3(), rotation=new Quaternion(), forward=new Vector3();
  const orbitPosition=new Vector3(),orbitQuaternion=new Quaternion();
  const reset=()=>{held.clear();last=null;pointer=null;};
  const turn=(axis,angle)=>{if(angle!==0)camera.quaternion.multiply(rotation.setFromAxisAngle(axis,angle)).normalize();};
  const value=(positive,negative)=>Number(held.has(positive))-Number(held.has(negative));
  const changeSpeed=factor=>{speed=Math.max(1,Math.min(1e9,speed*factor));};
  const down=event=>{
    if(!enabled || document.activeElement!==viewport || editable(event.target) || event.ctrlKey || event.metaKey || event.altKey || !keys.has(event.code))return;
    event.preventDefault();
    if(event.repeat)return;
    if(event.code==='Equal'||event.code==='NumpadAdd')changeSpeed(2);
    else if(event.code==='Minus'||event.code==='NumpadSubtract')changeSpeed(.5);
    else if(event.code==='Space')reset();
    else held.add(event.code);
  };
  const up=event=>held.delete(event.code);
  const focus=event=>{if(event.target!==viewport)reset();};
  const visibility=()=>{if(document.hidden)reset();};
  const pointerDown=event=>{
    if(!enabled || event.button!==0 || event.isPrimary===false)return;
    viewport.focus({preventScroll:true});pointer={id:event.pointerId,x:event.clientX,y:event.clientY,drag:false};
  };
  const pointerMove=event=>{
    if(!enabled||!pointer||event.pointerId!==pointer.id)return;
    const dx=event.clientX-pointer.x,dy=event.clientY-pointer.y;
    if(!pointer.drag && Math.hypot(dx,dy)<=5)return;
    pointer.drag=true;pointer.x=event.clientX;pointer.y=event.clientY;
    turn(axisY,-dx*.003);turn(axisX,-dy*.003);
  };
  const pointerUp=()=>{pointer=null;};
  const orbitChange=()=>{orbitSleeping=false;};
  controls.addEventListener?.('change',orbitChange);
  const bindings=[[window,'keydown',down],[window,'keyup',up],[window,'blur',reset],
    [document,'visibilitychange',visibility],[document,'focusin',focus],
    [viewport,'pointerdown',pointerDown],[window,'pointermove',pointerMove],
    [window,'pointerup',pointerUp],[window,'pointercancel',reset]];
  for(const [target,type,fn] of bindings)target.addEventListener(type,fn);
  return {
    get enabled(){return enabled;},
    setEnabled(value){
      if(enabled===value)return;
      reset();
      if(value){
        // Drain OrbitControls damping before handing over the camera.
        const position=camera.position.clone(),quaternion=camera.quaternion.clone();
        controls.enableDamping=false;controls.update();controls.enabled=false;
        camera.position.copy(position);camera.quaternion.copy(quaternion);
        viewport.focus({preventScroll:true});
      }else{
        orbitPosition.copy(camera.position);orbitQuaternion.copy(camera.quaternion);
        camera.up.copy(axisY).applyQuaternion(camera.quaternion);
        camera.getWorldDirection(forward);
        controls.target.copy(camera.position).addScaledVector(forward,12);
        controls.enabled=true;controls.enableDamping=true;controls.update();
        // OrbitControls clamps its spherical poles even without input. Keep
        // the exact flight pose until a genuine orbit gesture starts. Damping
        // was drained on entry, so there is no pending orbit motion to resume.
        camera.position.copy(orbitPosition);camera.quaternion.copy(orbitQuaternion);
        orbitSleeping=true;
      }
      enabled=value;
    },
    updateOrbit(){if(!orbitSleeping || controls.autoRotate)controls.update();},
    tick(now){
      if(!enabled)return;
      if(document.hidden){reset();return;}
      const dt=last===null?0:(now-last)/1000;last=now;
      // A suspended/blocked frame is not a travel command. No catch-up jump.
      if(dt<0 || dt>.25){reset();last=now;return;}
      turn(axisY,value('ArrowLeft','ArrowRight')*dt);
      turn(axisX,value('ArrowUp','ArrowDown')*dt);
      turn(axisZ,value('KeyQ','KeyE')*dt);
      movement.set(value('KeyD','KeyA'),value('KeyR','KeyF'),value('KeyS','KeyW'));
      if(movement.lengthSq()>0)camera.position.add(movement.normalize().applyQuaternion(camera.quaternion).multiplyScalar(speed*dt/KM_PER_RENDER_UNIT));
    },
    changeSpeed, stop:reset,
    inspect:()=>({enabled,speed,held:held.size}),
    dispose(){reset();controls.removeEventListener?.('change',orbitChange);for(const [target,type,fn] of bindings)target.removeEventListener(type,fn);},
  };
}
