/** Object selection and camera follow: handle selected object, follow mode. */

import { useEffect } from 'react';
import * as THREE from 'three';
import { applyViewState } from '../scene/viewState.js';
import { objectScale } from '../bodies/index.js';

export function useThreeFollow({ selected, follow, setView, setFollow, appRef, objects }) {
  // Select object -> focus camera on it, switch view if needed, enable follow
  useEffect(() => {
    const state = appRef.current;
    if (!state.scene || !selected) return;
    const mesh = state.meshes.get(selected.id);
    if (!mesh) return;
    const nextView = objectScale(selected);
    applyViewState(state, nextView);
    setView(nextView);
    const position = mesh.getWorldPosition(new THREE.Vector3());
    // displayRadius lives only on scaled scene objects; selected comes from catalog,
    // so we take radius from mesh userData.
    const radius = Math.max(mesh.userData?.displayRadius || 1, 0.1);
    // Large bodies (nebulae, galaxies) need more distance, otherwise camera ends up inside mesh.
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

  // Follow toggle -> update follow state without repositioning
  useEffect(() => {
    const state = appRef.current;
    state.followObject = selected;
    state.followCamera = follow && !!selected;
    state.lastFollowPos = null;
  }, [follow, selected, objects, appRef]);
}