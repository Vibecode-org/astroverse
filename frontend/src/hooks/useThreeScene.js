/** Scene initialization: create Three.js renderer, build all objects, start animation loop. */

import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { makeStarField, setSolarScale } from '../bodies/index.js';
import { makeMilkyWay } from '../bodies/meshes/milkyWayMesh.js';
import { disposeSceneResources } from '../bodies/resources.js';
import { createStage } from '../scene/stage.js';
import { buildSolarSystem, scaleCatalog } from '../scene/buildSolarSystem.js';
import { buildDeepSky } from '../scene/buildDeepSky.js';
import { attachPicking } from '../scene/picking.js';
import { startAnimationLoop } from '../scene/animation.js';
import { applyViewState } from '../scene/viewState.js';

const LIMITS = {
  real: { far: 4e6, maxDistance: 3e6, starField: 2e7, solarCam: [0, 9e4, 1.6e5] },
  compact: { far: 100000, maxDistance: 50000, starField: 18000, solarCam: [0, 65, 120] },
};

export function useThreeScene({ objects, solarScale, appRef, setErrorDetails, onPick, simDate }) {
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
        onPick,
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
      renderer?.domElement?.remove();
      if (scene) disposeSceneResources(scene);
      renderer?.dispose();
      appRef.current = {};
      console.error("Three.js Init Error:", err);
      setErrorDetails(err.name + ": " + err.message + "\n\nСтек:\n" + err.stack);
    }
  }, [objects, appRef, solarScale, setErrorDetails, onPick, simDate]);

  return { mountRef };
}