import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';

/** Renderer, camera, controls and the scene's two lights.
 *
 * Everything here is constructed inside the caller's `try` block, so a failure
 * (notably a missing WebGL context) unwinds through the same error path as the
 * rest of the scene build.
 */
export function createStage(el, limits) {
  const width = el.clientWidth || window.innerWidth;
  const height = el.clientHeight || window.innerHeight;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x010206);

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.05, limits.far);
  camera.position.set(...limits.solarCam);

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    powerPreference: 'high-performance',
    logarithmicDepthBuffer: true,
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(width, height);
  renderer.domElement.style.width = '100%';
  renderer.domElement.style.height = '100%';
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.25;

  if (el.childNodes.length > 0) el.innerHTML = '';
  el.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.minDistance = 0.05;
  controls.maxDistance = limits.maxDistance;
  controls.rotateSpeed = 0.55;
  controls.zoomSpeed = 0.7;
  controls.enablePan = true;
  controls.screenSpacePanning = true;

  const ambient = new THREE.AmbientLight(0x0e1322, 0.07);
  scene.add(ambient);

  // В «окрестностях Солнца» освещение даёт только ambient, а он почти чёрный:
  // экзопланеты выходят нечитаемыми. Светить от каждой из тысяч звёзд
  // непозволительно, поэтому в сцене ровно один источник — у хозяина
  // отслеживаемого объекта. Он включается только когда есть parent.
  const focusLight = new THREE.PointLight(0xfff2dd, 0, 0, 0);
  scene.add(focusLight);

  const sunLight = new THREE.PointLight(0xffffff, 3.2, 0, 0);
  sunLight.position.set(0, 0, 0);
  scene.add(sunLight);

  return { scene, camera, renderer, controls, ambient, focusLight, sunLight };
}
