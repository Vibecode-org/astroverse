import { useEffect, useRef } from 'react';
import { createStage } from '../scene/stage.js';
import { frameReadyAt } from './sectorManager.js';
import { physicalOffset } from './coordinates.js';
import { createFlight } from './flight.js';

export { createPhysicalLayer } from './physicalLayer.js';
import { createPhysicalLayer } from './physicalLayer.js';

export default function PhysicalScene({ frame, bodies = [], centerId, overview, onError, sceneRef, onNeighborhood, focusVersion = 0, selectedId = null, onPick, flying = false, onFlightStatus, onPresented }) {
  const neighborhoodRef = useRef(onNeighborhood);
  neighborhoodRef.current = onNeighborhood;
  const pickRef = useRef(onPick); pickRef.current = onPick;
  const statusRef = useRef(onFlightStatus); statusRef.current = onFlightStatus;
  const presentedRef=useRef(onPresented);presentedRef.current=onPresented;
  const mount = useRef(null);
  useEffect(() => {
    let stage, layer, raf;
    const el = mount.current;
    try {
      stage = createStage(el, { far: 1e12, maxDistance: 4e7, solarCam: [0, 8, 12] });
      const { scene, camera, renderer, controls } = stage;
      camera.near = 0.00001; camera.updateProjectionMatrix(); controls.minDistance = 0.0001;
      layer = createPhysicalLayer(scene);
      const flight=createFlight(camera,controls,el);
      const state = { ...stage, layer, flight, generation: 1, frames: 0, displayedAt:null, reference:null, rebases:0 };
      sceneRef.current = state;
      let lastStatus=0;
      const animate = (now=performance.now()) => {
        raf = requestAnimationFrame(animate);
        const start=performance.now();
        if(flight.enabled)flight.tick(now);else flight.updateOrbit();
        let rebased=false;
        if(state.reference && camera.position.length()>100){
          const shift=physicalOffset(camera.position);
          state.reference.offset=state.reference.offset.map((v,a)=>v+shift[a]);
          controls.target.sub(camera.position);camera.position.set(0,0,0);
          layer.rebase?.(shift);
          state.rebases++;rebased=true;
        }
        state.cameraMs=performance.now()-start;
        state.onCameraTiming?.(state.cameraMs);
        if(rebased)state.apply?.();
        layer.tick(camera, renderer.getPixelRatio?.() || 1); renderer.render(scene, camera);
        if(now-lastStatus>250){lastStatus=now;statusRef.current?.(flight.inspect());}
        if (state.pendingDisplay) {
          const {frame, ready} = state.pendingDisplay;
          state.displayedAt = frame.evaluated_at;
          presentedRef.current?.(frame);
          state.onTiming?.({kind:'display', ms:performance.now()-ready, at:frame.evaluated_at});
          state.pendingDisplay = null;
        }
        if (neighborhoodRef.current) {
          const offset = physicalOffset(camera.position);
          const origin=state.reference?state.reference.position.map((v,a)=>v+state.reference.offset[a]):null;
          const orbitRadius = camera.position.distanceTo(controls.target) * 2e5;
          if(state.reference && !flight.enabled)state.reference.radius=Math.max(state.reference.radius,orbitRadius);
          const radius = state.reference ? state.reference.radius : Math.max(2e6, orbitRadius);
          const previousNeighborhood=state.previousNeighborhood;
          const changed = !previousNeighborhood
            || !!origin!==!!previousNeighborhood.origin
            || Math.hypot(...offset.map((v,a)=>v-previousNeighborhood.offset[a]+(origin?.[a]||0)-(previousNeighborhood.origin?.[a]||0))) > radius/8
            || Math.abs(radius/previousNeighborhood.radius-1) > .25;
          if (changed) {
            state.previousNeighborhood = origin?{ offset, radius, origin }:{offset,radius};
            state.neighborhood = state.previousNeighborhood;
            neighborhoodRef.current(state.previousNeighborhood);
          }
        }
        state.frames++;
      };
      animate();
      const resize = () => {
        const w = el.clientWidth || 800, h = el.clientHeight || 600;
        camera.aspect = w / h; camera.updateProjectionMatrix(); renderer.setSize(w, h);
      };
      window.addEventListener('resize', resize);
      state.resize = resize;
      let pointerStart = null, dragged = false;
      const pointerDown = event => {
        if (event.isPrimary === false) { dragged = true; return; }
        pointerStart = [event.clientX, event.clientY]; dragged = event.button !== 0;
      };
      const pointerMove = event => {
        if (pointerStart && Math.hypot(event.clientX-pointerStart[0], event.clientY-pointerStart[1]) > 5) dragged = true;
      };
      const pointerCancel = () => { dragged = true; };
      el.addEventListener('pointerdown', pointerDown);
      window.addEventListener('pointermove', pointerMove);
      el.addEventListener('pointercancel', pointerCancel);
      window.addEventListener('blur',pointerCancel);
      document.addEventListener('visibilitychange',pointerCancel);
      state.releaseInputs = () => {
        el.removeEventListener('pointerdown', pointerDown);
        window.removeEventListener('pointermove', pointerMove);
        el.removeEventListener('pointercancel', pointerCancel);
        window.removeEventListener('blur',pointerCancel);
        document.removeEventListener('visibilitychange',pointerCancel);
      };
      const pick = event => {
        if (dragged || event.button !== 0) return;
        const rect = el.getBoundingClientRect();
        const id = layer.pick(camera, event.clientX-rect.left, event.clientY-rect.top, rect.width, rect.height);
        if (id) pickRef.current?.(id);
      };
      el.addEventListener('click', pick); state.pick = pick;
      onError(null, 'initialization');
    } catch (error) { onError(error.message, 'initialization'); }
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', sceneRef.current?.resize);
      el.removeEventListener('click', sceneRef.current?.pick);
      sceneRef.current?.releaseInputs();sceneRef.current?.flight.dispose();
      layer?.dispose();
      stage?.controls.dispose(); stage?.renderer.dispose(); stage?.renderer.domElement.remove();
      sceneRef.current = null;
    };
  }, [onError, sceneRef]);
  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    state.props={frame,centerId,overview,bodies,selectedId};
    state.apply=()=>{
      const p=state.props;
      if(state.reference)state.reference.cameraOffset=physicalOffset(state.camera.position);
      try{
        if(p.frame?.objects?.length>4096){
          const version=(state.applyVersion||0)+1;state.applyVersion=version;
          state.layer.prepare(p.frame,p.centerId,p.overview,state.neighborhood,p.bodies,p.selectedId,state.reference)
            .then(applied=>{if(applied && version===state.applyVersion){state.pendingDisplay={frame:p.frame,ready:frameReadyAt.get(p.frame)??performance.now()};onError(null,'frame');}})
            .catch(error=>{if(version===state.applyVersion){state.layer.update(null);state.displayedAt=null;presentedRef.current?.(null);onError(error.message,'frame');}});
          return false;
        }
        state.applyVersion=(state.applyVersion||0)+1;
        state.layer.update(p.frame,p.centerId,p.overview,state.neighborhood,p.bodies,p.selectedId,state.reference);
        if(p.frame && !state.reference)state.cameraChart=state.layer.cameraChart(p.centerId);
        return true;
      }catch(error){state.layer.update(null);onError(error.message,'frame');return false;}
    };
    state.pendingDisplay = null;
    if(!frame)state.displayedAt = null;
    if(!frame)presentedRef.current?.(null);
    if(state.apply()){
      state.pendingDisplay = frame ? {frame, ready:frameReadyAt.get(frame) ?? performance.now()} : null;
      if (frame) onError(null, 'frame');
    }
  }, [frame, bodies, centerId, overview, sceneRef, onError, selectedId]);
  useEffect(()=>{
    const state=sceneRef.current;if(!state)return;
    if(flying && !state.reference){
      // Retain just three chart records, never an evicted sector/frame graph.
      const chart=state.cameraChart||state.layer.cameraChart(centerId);
      // Preserve the orbit's loading reach on handoff, including a zoomed-out
      // view. Rebases/exit do not shrink it or change the physical camera.
      state.reference={...chart,offset:[...chart.offset],
        radius:Math.max(3e6,state.camera.position.distanceTo(state.controls.target)*2e5)};
      state.reference.cameraOffset=physicalOffset(state.camera.position);
      state.apply();
    }
    if(flying)state.reference.radius=Math.max(state.reference.radius,state.camera.position.distanceTo(state.controls.target)*2e5);
    state.flight.setEnabled(flying);
  },[flying,sceneRef]);
  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    state.flight.stop();state.reference=null;
    if(state.hasFocused){state.previousNeighborhood=null;state.neighborhood=null;}
    state.hasFocused=true;
    state.camera.up.set(0,1,0);
    state.controls.target.set(0, 0, 0);
    state.camera.position.set(...(overview ? (centerId === 'synthetic-origin' ? [0,8,24] : [0, 1800, 2400]) : [0, 8, 12]));
    state.controls.update();
    if(state.props?.frame?.objects?.length>4096){
      state.pendingDisplay=null;state.displayedAt=null;presentedRef.current?.(null);
      state.layer.update(null);
    }
    state.apply?.();
  }, [overview, centerId, focusVersion, sceneRef]);
  return <main ref={mount} className="viewport" tabIndex={0} aria-label="Проверенные геометрические центры" />;
}
