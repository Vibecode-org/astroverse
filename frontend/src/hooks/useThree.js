import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { makeMilkyWay, equatorialXYZ, galacticXYZ } from '../galaxy.js';
import { createBodyMesh, makeOrbit, makeAsteroidBelt, makeKuiperBelt, makeStarField, makeLabel, objectScale, getSolarDistance, getMoonOrbitDistance } from '../bodies/index.js';

export function useThree({ objects, view, setView, selected, setSelected, follow, setFollow, appRef, simDate, setErrorDetails }) {
  const mountRef = useRef(null);

  useEffect(() => {
    const el = mountRef.current;
    if (!el || !objects.length) return;

    let raf;
    let renderer;
    let controls;

    try {
      const width = el.clientWidth || window.innerWidth;
      const height = el.clientHeight || window.innerHeight;

      const scene = new THREE.Scene();
      scene.background = new THREE.Color(0x010206);

      const camera = new THREE.PerspectiveCamera(50, width / height, 0.05, 100000);
      camera.position.set(0, 65, 120);

      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(width, height);
      renderer.domElement.style.width = '100%';
      renderer.domElement.style.height = '100%';
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.25;

      if (el.childNodes.length > 0) el.innerHTML = '';
      el.appendChild(renderer.domElement);

      controls = new OrbitControls(camera, renderer.domElement);
      controls.enableDamping = true;
      controls.dampingFactor = 0.06;
      controls.minDistance = 0.05;
      controls.maxDistance = 50000;
      controls.rotateSpeed = 0.55;
      controls.zoomSpeed = 0.7;
      controls.enablePan = true;
      controls.screenSpacePanning = true;

      const ambient = new THREE.AmbientLight(0x0e1322, 0.07);
      scene.add(ambient);

      const sunLight = new THREE.PointLight(0xffffff, 3.2, 0, 0);
      sunLight.position.set(0, 0, 0);
      scene.add(sunLight);

      scene.add(makeStarField(10000, 18000));
      const galaxy = makeMilkyWay();
      scene.add(galaxy.group);

      const system = new THREE.Group();
      scene.add(system);
      const nearby = new THREE.Group();
      scene.add(nearby);
      const galaxyMarkers = new THREE.Group();
      scene.add(galaxyMarkers);

      const belt = makeAsteroidBelt();
      const kuiper = makeKuiperBelt();
      system.add(belt, kuiper);

      const meshes = new Map();
      const orbitLines = [];
      const labels = [];
      const moons = [];
      const blackHolesList = [];

      // Calculate scales for objects
      const scaledObjects = objects.map(obj => ({
        ...obj,
        scale: objectScale(obj)
      }));

      const solar = scaledObjects.filter((o) => o.scale === 'solar');
      const planets = {};

      solar.filter((o) => o.kind !== 'moon').forEach((obj) => {
        const mesh = createBodyMesh(obj);
        const dist = getSolarDistance(obj);
        mesh.userData.calculatedDistance = dist;
        mesh.userData.initialAngle = [...obj.id].reduce((angle, char) => angle + char.charCodeAt(0), 0) % 360 * Math.PI / 180;
        mesh.userData.currentAngle = mesh.userData.initialAngle;

        if (dist > 0) mesh.position.set(dist, 0, 0);
        system.add(mesh);
        meshes.set(obj.id, mesh);
        planets[obj.id] = mesh;

        if (['planet', 'dwarf_planet', 'asteroid'].includes(obj.kind) && dist > 0) {
          const orbit = makeOrbit(dist);
          system.add(orbit);
          orbitLines.push(orbit);
        }

        if (obj.kind !== 'star') {
          const label = makeLabel(obj.name);
          label.visible = false;
          scene.add(label);
          labels.push({ label, mesh, type: obj.kind, id: obj.id });
        }
      });

      solar.filter((o) => o.kind === 'moon').forEach((obj, idx) => {
        const parent = planets[obj.parent];
        const mesh = createBodyMesh(obj);
        const parentR = parent?.userData?.radius || 1.0;
        const moonDist = getMoonOrbitDistance(obj, parentR);

        const pivot = new THREE.Group();
        pivot.position.copy(parent ? parent.position : new THREE.Vector3());
        pivot.userData.initialAngle = (idx * 2.399) % (Math.PI * 2);

        mesh.position.set(moonDist, 0, 0);
        pivot.add(mesh);

        const moonOrbit = makeOrbit(moonDist, 0x334466, 0.25);
        pivot.add(moonOrbit);

        system.add(pivot);
        meshes.set(obj.id, mesh);
        moons.push({ pivot, mesh, obj, parentId: obj.parent });
      });

      scaledObjects.filter((o) => o.scale === 'local').forEach((obj) => {
        const mesh = createBodyMesh(obj);
        mesh.position.copy(equatorialXYZ(obj));
        nearby.add(mesh);
        meshes.set(obj.id, mesh);
      });

      scaledObjects.filter((o) => o.scale === 'galaxy').forEach((obj) => {
        const mesh = createBodyMesh(obj);
        mesh.position.copy(galacticXYZ(obj));
        galaxyMarkers.add(mesh);
        meshes.set(obj.id, mesh);

        if (mesh.userData?.isBlackHole) {
          blackHolesList.push(mesh.userData);
        }
      });

      const catalogByMesh = new Map(scaledObjects.map(obj => [meshes.get(obj.id), obj]));
      const raycaster = new THREE.Raycaster();
      raycaster.params.Points = { threshold: 1.2 };
      const pointer = new THREE.Vector2();

      let isDragging = false;
      let startX = 0;
      let startY = 0;

      const onPointerDown = (e) => {
        startX = e.clientX;
        startY = e.clientY;
        isDragging = false;
      };

      const onPointerMove = (e) => {
        if (Math.hypot(e.clientX - startX, e.clientY - startY) > 5) {
          isDragging = true;
        }
      };

      const onPointerUp = (event) => {
        if (isDragging) return;

        const rect = renderer.domElement.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(pointer, camera);

        const candidates = Array.from(meshes.values()).filter((m) => {
          let vis = m.visible;
          let p = m.parent;
          while (p) { vis = vis && p.visible; p = p.parent; }
          return vis;
        });

        const hit = raycaster.intersectObjects(candidates, true)[0];
        if (hit) {
          let mesh = hit.object;
          while (mesh && !catalogByMesh.has(mesh)) mesh = mesh.parent;
          const obj = catalogByMesh.get(mesh);
          if (obj) {
            setView(objectScale(obj));
            setSelected(obj);
            setFollow(true);
          }
        }
      };

      renderer.domElement.addEventListener('pointerdown', onPointerDown);
      renderer.domElement.addEventListener('pointermove', onPointerMove);
      renderer.domElement.addEventListener('pointerup', onPointerUp);

      appRef.current = {
        scene, camera, renderer, controls, meshes, orbitLines, galaxy, nearby,
        system, galaxyMarkers, labels, moons, planets, view: 'solar', sunLight, ambient, belt, kuiper,
        simTime: simDate.getTime(),
      };

      applyViewState(appRef.current, 'solar');

      const animate = () => {
        raf = requestAnimationFrame(animate);

        const state = appRef.current;

        const days = (state.simTime - Date.UTC(2000, 0, 1, 12)) / 86400000;
        // Deterministic illustrative orbits: date jumps and reverse time use the same positions.

          solar.forEach((obj) => {
            const mesh = meshes.get(obj.id);
            if (!mesh || obj.kind === 'moon') return;
            const dist = mesh.userData.calculatedDistance;
            const periodDays = obj.period_days || (obj.au ? 365.25 * Math.pow(obj.au, 1.5) : 365);

            if (['planet', 'dwarf_planet', 'asteroid'].includes(obj.kind) && dist > 0) {
              mesh.userData.currentAngle = mesh.userData.initialAngle + (days / periodDays) * Math.PI * 2;
              mesh.position.x = Math.cos(mesh.userData.currentAngle) * dist;
              mesh.position.z = Math.sin(mesh.userData.currentAngle) * dist * 0.995;
            }
            mesh.rotation.y = days * 0.2;
          });

          moons.forEach(({ pivot, mesh, obj, parentId }) => {
            const parent = meshes.get(parentId);
            if (parent) pivot.position.copy(parent.position);
            const period = obj.period_days || 27.3;
            pivot.rotation.y = pivot.userData.initialAngle + (days / period) * Math.PI * 2;
            mesh.rotation.y = days * 0.3;
          });

          blackHolesList.forEach(({ disk, lensHalo, photonRing }) => {
            if (disk) disk.rotation.z = days * 0.45;
            if (lensHalo) lensHalo.rotation.z = -days * 0.25;
            if (photonRing) photonRing.quaternion.copy(camera.quaternion);
          });

          labels.forEach(({ label, mesh, type, id }) => {
            const world = new THREE.Vector3();
            mesh.getWorldPosition(world);
            label.position.copy(world).add(new THREE.Vector3(0, (mesh.userData.radius || 1) + 1.2, 0));
            label.quaternion.copy(camera.quaternion);
            const isCurrentSelected = state.followObject && state.followObject.id === id;
            label.visible = state.view === 'solar' && ['planet', 'dwarf_planet'].includes(type) && !isCurrentSelected;
          });



          if (state.followObject && meshes.has(state.followObject.id)) {
            const m = meshes.get(state.followObject.id);
            const currentPos = new THREE.Vector3();
            m.getWorldPosition(currentPos);

            if (state.followCamera) {
              if (!state.lastFollowPos) {
                state.lastFollowPos = currentPos.clone();
              }
              const delta = currentPos.clone().sub(state.lastFollowPos);
              camera.position.add(delta);
              controls.target.add(delta);
              state.lastFollowPos.copy(currentPos);
            } else {
              state.lastFollowPos = null;
            }
          } else {
            state.lastFollowPos = null;
          }

          controls.update();
          renderer.render(scene, camera);
      };
      animate();

      const resize = () => {
        const w = el.clientWidth || window.innerWidth;
        const h = el.clientHeight || window.innerHeight;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      };
      window.addEventListener('resize', resize);

      return () => {
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', resize);
        if (renderer?.domElement) {
          renderer.domElement.removeEventListener('pointerdown', onPointerDown);
          renderer.domElement.removeEventListener('pointermove', onPointerMove);
          renderer.domElement.removeEventListener('pointerup', onPointerUp);
          if (el.contains(renderer.domElement)) {
            el.removeChild(renderer.domElement);
          }
        }
        controls.dispose();
        scene.traverse(object => {
          object.geometry?.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach(material => material?.dispose());
        });
        renderer?.dispose();
        appRef.current = {};
      };
    } catch (err) {
      cancelAnimationFrame(raf);
      controls?.dispose();
      renderer?.domElement.remove();
      renderer?.dispose();
      appRef.current = {};
      console.error("Three.js Init Error:", err);
      setErrorDetails(err.name + ": " + err.message + "\n\nСтек:\n" + err.stack);
    }
  }, [objects, appRef]);

  useEffect(() => {
    const state = appRef.current;
    if (!state.scene) return;
    applyViewState(state, view);
    state.followObject = null;
    state.followCamera = false;
    state.lastFollowPos = null;
    state.controls.target.set(0, 0, 0);
    if (view === 'galaxy') state.camera.position.set(0, 220, 350);
    else if (view === 'local') state.camera.position.set(0, 35, 70);
    else state.camera.position.set(0, 65, 120);
    state.controls.update();
  }, [view, objects, appRef]);

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
    const radius = Math.max(selected.radius || mesh.userData.radius || 1, 0.1);
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

function applyViewState(s, nextView) {
  if (!s.scene) return;
  s.view = nextView;
  s.system.visible = nextView === 'solar';
  s.nearby.visible = nextView === 'local';
  s.galaxy.group.visible = nextView === 'galaxy';
  s.galaxyMarkers.visible = nextView === 'galaxy';
  if (s.sunLight) {
    s.sunLight.visible = nextView === 'solar';
    s.ambient.intensity = nextView === 'solar' ? 0.07 : nextView === 'local' ? 0.5 : 0.7;
  }
}