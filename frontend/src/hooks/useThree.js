import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { makeStarField, setSolarScale, objectScale } from '../bodies/index.js';
import { makeMilkyWay } from '../bodies/meshes/milkyWayMesh.js';
import { disposeSceneResources } from '../bodies/resources.js';
import { createStage } from '../scene/stage.js';
import { buildSolarSystem, scaleCatalog } from '../scene/buildSolarSystem.js';
import { buildDeepSky } from '../scene/buildDeepSky.js';
import { attachPicking } from '../scene/picking.js';
import { startAnimationLoop } from '../scene/animation.js';
import { applyViewState } from '../scene/viewState.js';

/** World bounds for the active scale mode.
 *
 * In real scale Neptune sits at 704 000 Earth radii, so the depth buffer has to
 * be logarithmic (see the renderer options) and the far plane has to be huge;
 * the compact mode keeps everything in a single frame instead.
 */
const LIMITS = {
  real: { far: 4e6, maxDistance: 3e6, starField: 2e7, solarCam: [0, 9e4, 1.6e5] },
  compact: { far: 100000, maxDistance: 50000, starField: 18000, solarCam: [0, 65, 120] },
};

/** Mounts the Three.js scene and keeps it in sync with the UI state.
 *
 * The scene itself is built exactly once per (objects, solarScale) pair and
 * then mutated in place; everything else — view switching, selection, follow —
 * is handled by the effects below, which only touch the shared `appRef`
 * state object. That split is what keeps a 10 Hz time engine from rebuilding
 * 3471 meshes every tick.
 */
export function useThree({ objects, view, setView, selected, setSelected, follow, setFollow, appRef, simDate, setErrorDetails, solarScale }) {
  const mountRef = useRef(null);

  useEffect(() => {
    const el = mountRef.current;
    if (!el || !objects.length) return;

    setSolarScale(solarScale);
    const limits = LIMITS[solarScale] || LIMITS.real;

    let stopAnimation = null;
    let detachPicking = null;
    let renderer;
    let controls;
    let scene;
    let onResize = null;

    try {
      const stage = createStage(el, limits);
      ({ renderer, controls, scene } = stage);
      const { camera, ambient, focusLight, sunLight } = stage;

      scene.add(makeStarField(10000, limits.starField));
      const galaxy = makeMilkyWay();
      scene.add(galaxy.group);

      // One group per scale; applyViewState toggles their visibility.
      const system = new THREE.Group();
      scene.add(system);
      const nearby = new THREE.Group();
      scene.add(nearby);
      const galaxyMarkers = new THREE.Group();
      scene.add(galaxyMarkers);

      const scaledObjects = scaleCatalog(objects);

      const solarBuilt = buildSolarSystem(scaledObjects, system, scene);
      const { meshes, orbitLines, labels, moons, planets, solar, belt, kuiper } = solarBuilt;
      const { localOrbits, blackHolesList } = buildDeepSky(scaledObjects, nearby, galaxyMarkers, meshes);

      const catalogByMesh = new Map(scaledObjects.map(obj => [meshes.get(obj.id), obj]));
      detachPicking = attachPicking({
        domElement: renderer.domElement,
        camera,
        meshes,
        catalogByMesh,
        onPick: (obj, scale) => {
          setView(scale);
          setSelected(obj);
          setFollow(true);
        },
      });

      appRef.current = {
        scene, camera, renderer, controls, meshes, orbitLines, galaxy, nearby,
        system, galaxyMarkers, labels, moons, planets, localOrbits, view: 'solar',
        sunLight, ambient, focusLight, belt, kuiper, limits,
        simTime: simDate.getTime(),
      };

      applyViewState(appRef.current, 'solar');

      stopAnimation = startAnimationLoop({
        state: appRef.current, camera, controls, renderer, scene,
        solar, meshes, moons, localOrbits, blackHolesList, labels,
      });

      const resize = () => {
        const w = el.clientWidth || window.innerWidth;
        const h = el.clientHeight || window.innerHeight;
        if (!w || !h) return;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      };
      window.addEventListener('resize', resize);
      onResize = resize;

      return () => {
        stopAnimation?.();
        if (onResize) window.removeEventListener('resize', onResize);
        detachPicking?.();
        renderer?.domElement?.remove();
        controls?.dispose();
        if (scene) disposeSceneResources(scene);
        renderer?.dispose();
        appRef.current = {};
      };
    } catch (err) {
      stopAnimation?.();
      if (onResize) window.removeEventListener('resize', onResize);
      detachPicking?.();
      controls?.dispose();
      // The renderer may not exist yet, so guard the DOM handle as well.
      renderer?.domElement?.remove();
      if (scene) disposeSceneResources(scene);
      renderer?.dispose();
      appRef.current = {};
      console.error("Three.js Init Error:", err);
      setErrorDetails(err.name + ": " + err.message + "\n\nСтек:\n" + err.stack);
    }
  }, [objects, appRef, solarScale]);

  // Switching scale resets the camera and drops any follow target, otherwise
  // the previous scale's camera position is kept and the new view opens off-screen.
  useEffect(() => {
    const state = appRef.current;
    if (!state.scene) return;
    applyViewState(state, view);
    state.followObject = null;
    state.followCamera = false;
    state.lastFollowPos = null;
    state.controls.target.set(0, 0, 0);
    // Позиция камеры задаётся теми же пределами, что и при создании сцены:
    // в реальном масштабе (0, 65, 120) — это камера внутри Солнца.
    const solarCam = state.limits?.solarCam || LIMITS.real.solarCam;
    if (view === 'galaxy') state.camera.position.set(0, 220, 350);
    else if (view === 'local') state.camera.position.set(0, 35, 70);
    else state.camera.position.set(...solarCam);
    state.controls.update();
  }, [view, objects, appRef, solarScale]);

  // The time engine ticks at 10 Hz; only the timestamp is handed to the loop.
  useEffect(() => {
    appRef.current.simTime = simDate.getTime();
  }, [simDate, objects, appRef]);

  useEffect(() => {
    const state = appRef.current;
    if (!state.scene || !selected) return;
    const mesh = state.meshes.get(selected.id);
    if (!mesh) return;
    const nextView = objectScale(selected);
    applyViewState(state, nextView);
    setView(nextView);
    const position = mesh.getWorldPosition(new THREE.Vector3());
    // displayRadius живёт только на масштабированных объектах сцены, а selected
    // приходит прямо из каталога, поэтому берём радиус из userData меша.
    const radius = Math.max(mesh.userData?.displayRadius || 1, 0.1);
    // Крупные тела (туманности, галактики) требуют большего отлёта, иначе
    // камера оказывается внутри их меша.
    const isBig = ['cluster', 'nebula', 'galaxy', 'black_hole'].includes(selected.kind);
    const distance = radius * (isBig ? 4.2 : 2.8);
    state.controls.target.copy(position);
    state.camera.position.copy(position).add(new THREE.Vector3(distance, distance * 0.4, distance * 1.15));
    state.controls.update();
    state.followObject = selected;
    state.followCamera = true;
    state.lastFollowPos = position.clone();
    setFollow(true);
  }, [selected, objects, appRef, setView, setFollow]);

  useEffect(() => {
    const state = appRef.current;
    state.followObject = selected;
    state.followCamera = follow && !!selected;
    state.lastFollowPos = null;
  }, [follow, selected, objects, appRef]);

  return { mountRef };
}
