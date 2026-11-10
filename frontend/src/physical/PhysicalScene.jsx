import { useEffect, useRef } from 'react';
import { createStage } from '../scene/stage.js';
import { physicalOffset } from './coordinates.js';

export { createPhysicalLayer } from './physicalLayer.js';
import { createPhysicalLayer } from './physicalLayer.js';

export default function PhysicalScene({ frame, bodies = [], centerId, overview, onError, sceneRef, onNeighborhood, focusVersion = 0, selectedId = null, onPick }) {
  const neighborhoodRef = useRef(onNeighborhood);
  neighborhoodRef.current = onNeighborhood;
  const pickRef = useRef(onPick); pickRef.current = onPick;
  const mount = useRef(null);
  useEffect(() => {
    let stage, layer, raf;
    const el = mount.current;
    try {
      stage = createStage(el, { far: 1e12, maxDistance: 4e7, solarCam: [0, 8, 12] });
      const { scene, camera, renderer, controls } = stage;
      camera.near = 0.00001; camera.updateProjectionMatrix(); controls.minDistance = 0.0001;
      layer = createPhysicalLayer(scene);
      const state = { ...stage, layer, generation: 1, frames: 0 };
      sceneRef.current = state;
      let previousNeighborhood = null;
      const animate = () => {
        raf = requestAnimationFrame(animate);
        controls.update(); layer.tick(camera, renderer.getPixelRatio?.() || 1); renderer.render(scene, camera);
        if (neighborhoodRef.current) {
          const offset = physicalOffset(camera.position);
          const radius = Math.max(2e6, camera.position.distanceTo(controls.target) * 2e5);
          const changed = !previousNeighborhood
            || Math.hypot(...offset.map((v,a)=>v-previousNeighborhood.offset[a])) > radius/8
            || Math.abs(radius/previousNeighborhood.radius-1) > .25;
          if (changed) {
            previousNeighborhood = { offset, radius };
            state.neighborhood = previousNeighborhood;
            neighborhoodRef.current(previousNeighborhood);
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
      el.addEventListener('pointermove', pointerMove);
      el.addEventListener('pointercancel', pointerCancel);
      state.releaseInputs = () => {
        el.removeEventListener('pointerdown', pointerDown);
        el.removeEventListener('pointermove', pointerMove);
        el.removeEventListener('pointercancel', pointerCancel);
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
      sceneRef.current?.releaseInputs();
      layer?.dispose();
      stage?.controls.dispose(); stage?.renderer.dispose(); stage?.renderer.domElement.remove();
      sceneRef.current = null;
    };
  }, [onError, sceneRef]);
  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    try {
      state.layer.update(frame, centerId, overview, state.neighborhood, bodies, selectedId);
      if (frame) onError(null, 'frame');
    } catch (error) { state.layer.update(null); onError(error.message, 'frame'); }
  }, [frame, bodies, centerId, overview, sceneRef, onError, selectedId]);
  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    state.controls.target.set(0, 0, 0);
    state.camera.position.set(...(overview ? [0, 1800, 2400] : [0, 8, 12]));
    state.controls.update();
  }, [overview, centerId, focusVersion, sceneRef]);
  return <main ref={mount} className="viewport" aria-label="Проверенные геометрические центры" />;
}
