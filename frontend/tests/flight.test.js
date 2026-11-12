import { it, expect, vi } from 'vitest';
import { PerspectiveCamera, Vector3, Euler } from 'three';
import { createFlight } from '../src/physical/flight.js';
import { physicalFrame, relativeToReference, renderPosition } from '../src/physical/coordinates.js';
import fixture from '../../tests/fixtures/physical_hierarchy_synthetic.json';
import { createPhysicalLayer } from '../src/physical/physicalLayer.js';
import { Scene } from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

function setup(real=false){
 const camera=new PerspectiveCamera();
 const el=document.createElement('main');el.tabIndex=0;document.body.append(el);
 const controls=real?new OrbitControls(camera,el):{target:new Vector3(),update:vi.fn(),enabled:true,enableDamping:true};
 const flight=createFlight(camera,controls,el);flight.setEnabled(true);
 return {camera,controls,el,flight,end(){flight.dispose();controls.dispose?.();el.remove();}};
}
const key=(code,type='keydown',options={})=>window.dispatchEvent(new KeyboardEvent(type,{code,bubbles:true,cancelable:true,...options}));
const near=(a,b,tolerance=1e-10)=>expect(a.distanceTo(b)).toBeLessThan(tolerance);
it('travels along all six local directions after combined yaw/pitch/roll',()=>{
 const s=setup();s.camera.quaternion.setFromEuler(new Euler(.7,-1.1,1.3));
 for(const [code,axis] of [['KeyW',[0,0,-1]],['KeyS',[0,0,1]],['KeyA',[-1,0,0]],['KeyD',[1,0,0]],['KeyR',[0,1,0]],['KeyF',[0,-1,0]]]){
  s.flight.stop();s.camera.position.set(0,0,0);key(code);s.flight.tick(0);s.flight.tick(100);
  near(s.camera.position,new Vector3(...axis).applyQuaternion(s.camera.quaternion).multiplyScalar(.1));key(code,'keyup');
 }
 key('KeyW');key('KeyD');s.flight.stop();s.camera.position.set(0,0,0);key('KeyW');key('KeyD');s.flight.tick(0);s.flight.tick(100);
 expect(s.camera.position.length()).toBeCloseTo(.1,12);s.end();
});
it('uses elapsed real seconds at 30/60/144 Hz and ignores suspended frames without catch-up',()=>{
 for(const hz of [30,60,144]){
  const s=setup();key('KeyW');s.flight.tick(0);for(let i=1;i<=hz;i++)s.flight.tick(i*1000/hz);
  near(s.camera.position,new Vector3(0,0,-1));
  const before=s.camera.position.clone();s.flight.tick(5000);s.flight.tick(5016);near(s.camera.position,before);
  expect(s.flight.inspect().held).toBe(0);key('KeyW', 'keydown',{repeat:true});s.flight.tick(5032);near(s.camera.position,before);
  key('KeyW');s.flight.tick(5048);expect(s.camera.position.z).toBeLessThan(before.z);
  s.flight.tick(5000);expect(s.flight.inspect().held).toBe(0);s.end();
 }
});
it('rotates around local yaw/pitch/roll axes and moves in the resulting forward direction',()=>{
 for(const code of ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','KeyQ','KeyE']){
  const s=setup();key(code);s.flight.tick(0);s.flight.tick(200);key(code,'keyup');
  expect(s.camera.quaternion.angleTo(new PerspectiveCamera().quaternion)).toBeCloseTo(.2,12);
  key('KeyW');const forward=s.camera.getWorldDirection(new Vector3());s.flight.tick(220);
  near(s.camera.position,forward.multiplyScalar(.02));s.end();
 }
});
it('brakes, bounds speed, ignores repeat/modifiers and does not fly while typing',()=>{
 const s=setup();key('Equal');expect(s.flight.inspect().speed).toBe(200000);key('Minus');key('NumpadSubtract');key('NumpadAdd');
 expect(s.flight.inspect().speed).toBe(100000);
 s.flight.changeSpeed(1e20);expect(s.flight.inspect().speed).toBe(1e9);s.flight.changeSpeed(1e-30);expect(s.flight.inspect().speed).toBe(1);
 key('KeyW');key('Space');s.flight.tick(0);s.flight.tick(100);near(s.camera.position,new Vector3());
 for(const tag of ['input','textarea','select','div']){
  const input=document.createElement(tag);input.tabIndex=0;if(tag==='div')input.contentEditable='true';document.body.append(input);input.focus();
  input.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyW',bubbles:true}));s.flight.tick(120);near(s.camera.position,new Vector3());input.remove();
 }
 s.el.focus();for(const options of [{ctrlKey:true},{metaKey:true},{altKey:true}])key('KeyW','keydown',options);
 key('KeyZ');s.flight.tick(140);near(s.camera.position,new Vector3());s.end();
});
it('clears input on blur, hidden tab, pointer cancel and handoff, then disposes every listener',()=>{
 const s=setup();
 for(const event of ['blur','pointercancel']){key('KeyW');window.dispatchEvent(new Event(event));expect(s.flight.inspect().held).toBe(0);}
 key('KeyW');vi.spyOn(document,'hidden','get').mockReturnValue(true);document.dispatchEvent(new Event('visibilitychange'));s.flight.tick(0);expect(s.flight.inspect().held).toBe(0);
 vi.spyOn(document,'hidden','get').mockReturnValue(false);
 expect(s.controls.enabled).toBe(false);s.camera.quaternion.setFromEuler(new Euler(.2,.3,.5));const before=s.camera.quaternion.clone();
 s.flight.setEnabled(false);expect(s.controls.enabled).toBe(true);expect(s.camera.quaternion.equals(before)).toBe(true);
 s.flight.setEnabled(false);s.flight.tick(10);key('KeyW');expect(s.flight.inspect().held).toBe(0);
 const removeWindow=vi.spyOn(window,'removeEventListener'),removeDoc=vi.spyOn(document,'removeEventListener'),removeEl=vi.spyOn(s.el,'removeEventListener');
 s.end();expect(removeWindow).toHaveBeenCalledTimes(6);expect(removeDoc).toHaveBeenCalledTimes(2);expect(removeEl).toHaveBeenCalledOnce();
});
it('mouse drag has a threshold, uses local rotations and cancels cleanly',()=>{
 const s=setup(),send=(type,x,y,id=1,button=0)=>{
  const e=new MouseEvent(type,{clientX:x,clientY:y,button,bubbles:true});Object.defineProperty(e,'pointerId',{value:id});s.el.dispatchEvent(e);
 };
 send('pointerdown',0,0);send('pointermove',3,0);expect(s.camera.quaternion.w).toBe(1);
 send('pointermove',10,5,2);expect(s.camera.quaternion.w).toBe(1);
 send('pointermove',10,5);expect(s.camera.quaternion.w).toBeLessThan(1);
 send('pointerup',10,5);const q=s.camera.quaternion.clone();send('pointermove',20,20);expect(s.camera.quaternion.equals(q)).toBe(true);
 send('pointerdown',0,0,1,2);send('pointermove',50,50);expect(s.camera.quaternion.equals(q)).toBe(true);s.end();
});
it('preserves the exact pose at both OrbitControls poles until actual orbit input starts',()=>{
 for(const pitch of [Math.PI/2,-Math.PI/2,.3]){
  const s=setup(true);s.camera.position.set(40,-20,3);
  s.camera.quaternion.setFromEuler(new Euler(pitch,0,.4));
  const position=s.camera.position.clone(),quaternion=s.camera.quaternion.clone();
  s.flight.setEnabled(false);
  for(let i=0;i<100;i++)s.flight.updateOrbit();
  s.controls.dispatchEvent({type:'start'});s.flight.updateOrbit();
  near(s.camera.position,position,1e-12);expect(s.camera.quaternion.equals(quaternion)).toBe(true);
  const update=vi.spyOn(s.controls,'update');s.controls.dispatchEvent({type:'change'});s.flight.updateOrbit();
  expect(update).toHaveBeenCalledOnce();s.end();
 }
 const s=setup(true);s.flight.setEnabled(false);const update=vi.spyOn(s.controls,'update');
 s.controls.autoRotate=true;s.flight.updateOrbit();expect(update).toHaveBeenCalledOnce();s.end();
});
it('frozen charts preserve centers and sub-ULP offsets at 1e18 km through rebasing and time/address updates',()=>{
 const frame=structuredClone(fixture.frame);
 for(const sector of frame.hierarchy.sectors)if(sector.origin_km)sector.origin_km=sector.origin_km.map(v=>v+1e18);
 for(const row of frame.objects)if(row.position)row.position=row.position.map(v=>v+1e18);
 const original=JSON.stringify(frame),layer=createPhysicalLayer(new Scene());layer.update(frame,'a',true);
 const reference=layer.cameraChart('a');reference.cameraOffset=[0,0,0];
 const parsed=physicalFrame(frame),relative=relativeToReference(parsed.rows[1],parsed.hierarchy,reference);
 expect(relative).toEqual([.125,.5,1]);
 layer.update(frame,'a',true,null,[],null,reference);
 const before=layer.inspect().rows;
 for(const offset of [[3e6,-2e6,1e6],[0,0,0]]){
  reference.offset=offset;layer.update(frame,'a',true,null,[],null,reference);
  expect(layer.inspect().rows).toEqual(before);
  const expected=renderPosition(relativeToReference(parsed.rows[1],parsed.hierarchy,reference),[0,0,0]);
  layer.inspect().render.slice(3,6).forEach((v,a)=>expect(Math.abs(v-expected[a])).toBeLessThan(2e-6));
 }
 const moved=structuredClone(frame);moved.hierarchy.bodies[1].offset_km[0]+=.25;
 const next=physicalFrame(moved);expect(relativeToReference(next.rows[1],next.hierarchy,reference)[0]).toBe(.375);
 expect(JSON.stringify(frame)).toBe(original);layer.dispose();
});
