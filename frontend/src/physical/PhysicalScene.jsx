import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { createStage } from '../scene/stage.js';
import { renderPosition, physicalFrame, physicalOffset } from './coordinates.js';

/** Incremental body membership. No orbit phases, surfaces, or catalog layout. */
export function createPhysicalLayer(scene) {
  let geometry = new THREE.BufferGeometry();
  let capacity = 8;
  // Capacity follows the explicit supported body set; no per-frame allocation.
  let positions = new Float32Array(capacity * 3), colors = new Float32Array(capacity * 3);
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geometry.setDrawRange(0, 0);
  const material = new THREE.PointsMaterial({ size: 9, sizeAttenuation: false, vertexColors: true });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  scene.add(points);
  let rows = [], origin = [0, 0, 0], hierarchy = null;
  return {
    update(frame, centerId, overview = false, neighborhood = null, bodies = []) {
      const COLORS = Object.fromEntries(bodies.map(body => [body.id, body.color]));
      const parsed = frame ? physicalFrame(frame) : {rows:[],hierarchy:null};
      rows = parsed.rows; hierarchy = parsed.hierarchy;
      if (rows.length > 4096) throw new Error('Слишком много центров в positions/1');
      if (rows.length > capacity) {
        while (capacity < rows.length) capacity *= 2;
        const old = geometry;
        geometry = new THREE.BufferGeometry();
        positions = new Float32Array(capacity * 3); colors = new Float32Array(capacity * 3);
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
        points.geometry = geometry;
        old.dispose();
      }
      if (frame) origin = rows.find(row => row.id === centerId)?.position || origin;
      const relative = row => hierarchy?.relative(row.id,centerId) || row.position.map((v,a)=>v-origin[a]);
      if (!overview) rows = rows.filter(row => Math.hypot(...relative(row).map((v,a)=>
        v - (neighborhood?.offset[a] || 0))) <= (neighborhood?.radius ?? 2e6));
      rows.forEach((row, i) => {
        positions.set(renderPosition(relative(row), [0,0,0]), i * 3);
        const color = new THREE.Color(COLORS[row.id] || '#ffffff');
        colors.set([color.r, color.g, color.b], i * 3);
      });
      geometry.attributes.position.needsUpdate = true;
      geometry.attributes.color.needsUpdate = true;
      geometry.setDrawRange(0, rows.length);
      points.visible = rows.length > 0;
    },
    inspect: () => ({ origin: [...origin], rows: rows.map(row => ({ id: row.id, position: [...row.position] })),
      render: Array.from(positions.slice(0, rows.length * 3)),
      hierarchy: hierarchy ? {binding:hierarchy.binding, addresses:rows.map(row=>hierarchy.address(row.id))} : null }),
    dispose() { scene.remove(points); geometry.dispose(); material.dispose(); rows = []; hierarchy = null; },
  };
}

export default function PhysicalScene({ frame, bodies = [], centerId, overview, onError, sceneRef, onNeighborhood, focusVersion = 0 }) {
  const neighborhoodRef = useRef(onNeighborhood);
  neighborhoodRef.current = onNeighborhood;
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
        controls.update(); renderer.render(scene, camera);
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
      onError(null, 'initialization');
    } catch (error) { onError(error.message, 'initialization'); }
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', sceneRef.current?.resize);
      layer?.dispose();
      stage?.controls.dispose(); stage?.renderer.dispose(); stage?.renderer.domElement.remove();
      sceneRef.current = null;
    };
  }, [onError, sceneRef]);
  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    try {
      state.layer.update(frame, centerId, overview, state.neighborhood, bodies);
      if (frame) onError(null, 'frame');
    } catch (error) { state.layer.update(null); onError(error.message, 'frame'); }
  }, [frame, bodies, centerId, overview, sceneRef, onError]);
  useEffect(() => {
    const state = sceneRef.current;
    if (!state) return;
    state.controls.target.set(0, 0, 0);
    state.camera.position.set(...(overview ? [0, 1800, 2400] : [0, 8, 12]));
    state.controls.update();
  }, [overview, centerId, focusVersion, sceneRef]);
  return <main ref={mount} className="viewport" aria-label="Проверенные геометрические центры" />;
}
