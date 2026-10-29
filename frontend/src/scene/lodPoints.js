/** L0: one `THREE.Points` cloud for every deep-sky object.
 *
 * Point size and fade are computed on the GPU from the object's world-space
 * radius, so a camera move does not require rewriting a size attribute for
 * every object. The CPU only uploads positions of objects that actually move
 * (exoplanets on their orbits).
 */

import * as THREE from 'three';

const VERTEX_SHADER = `
attribute vec3 aColor;
attribute float aRadius;

uniform float uFocal;
uniform float uL1Enter;
uniform float uL1Exit;

varying vec3 vColor;
varying float vAlpha;

void main() {
  vColor = aColor;

  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mvPosition;

  // Projected radius in pixels. L0 owns objects below L1_ENTER; as the object
  // approaches the threshold the point fades out and L1 fades in, so the
  // hand-off does not snap.
  float radiusPx = aRadius * uFocal / max(-mvPosition.z, 0.0001);
  vAlpha = 1.0 - smoothstep(uL1Exit, uL1Enter, radiusPx);

  // A floor keeps sub-pixel stars visible; the ceiling prevents a point from
  // covering the screen just before the L1 hand-off.
  gl_PointSize = clamp(radiusPx * 2.0, 1.5, 7.0);

  if (vAlpha <= 0.01) {
    // Clip completely instead of drawing a transparent 1 px quad.
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
  }
}
`;

const FRAGMENT_SHADER = `
varying vec3 vColor;
varying float vAlpha;

void main() {
  vec2 offset = gl_PointCoord - vec2(0.5);
  float dist = length(offset);
  if (dist > 0.5) discard;

  // Soft edge: a hard circle aliases badly at 2–3 px.
  float alpha = (1.0 - smoothstep(0.32, 0.5, dist)) * vAlpha;

  gl_FragColor = vec4(vColor, alpha);

  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}
`;

export function createLODPoints(objects) {
  const count = objects.length;

  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  const radii = new Float32Array(count);

  objects.forEach((obj, i) => {
    const color = new THREE.Color(obj.color || '#ffffff');
    colors[i * 3] = color.r;
    colors[i * 3 + 1] = color.g;
    colors[i * 3 + 2] = color.b;
    radii[i] = obj.displayRadius ?? obj.radius ?? 0.4;
  });

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute('aRadius', new THREE.BufferAttribute(radii, 1));

  const material = new THREE.ShaderMaterial({
    vertexShader: VERTEX_SHADER,
    fragmentShader: FRAGMENT_SHADER,
    uniforms: {
      uFocal: { value: 1000 },
      uL1Enter: { value: 3.0 },
      uL1Exit: { value: 2.0 },
    },
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });

  const points = new THREE.Points(geometry, material);
  // Positions are updated in place, so a stale bounding sphere would cull the
  // whole cloud as soon as one object left its initial box.
  points.frustumCulled = false;
  points.userData = { lodLevel: 0, objectCount: count };

  let positionsDirty = false;

  return {
    object: points,

    setPosition(index, position) {
      positions[index * 3] = position.x;
      positions[index * 3 + 1] = position.y;
      positions[index * 3 + 2] = position.z;
      positionsDirty = true;
    },

    commit() {
      if (!positionsDirty) return;
      geometry.attributes.position.needsUpdate = true;
      positionsDirty = false;
    },

    setViewport(focal) {
      material.uniforms.uFocal.value = focal;
    },

    dispose() {
      geometry.dispose();
      material.dispose();
    },
  };
}
