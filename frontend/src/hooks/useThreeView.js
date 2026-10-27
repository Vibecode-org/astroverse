/** View switching: handle solar/local/galaxy view changes, camera positioning. */

import { useEffect } from 'react';
import { applyViewState } from '../scene/viewState.js';

const LIMITS = {
  real: { far: 4e6, maxDistance: 3e6, starField: 2e7, solarCam: [0, 9e4, 1.6e5] },
  compact: { far: 100000, maxDistance: 50000, starField: 18000, solarCam: [0, 65, 120] },
};

export function useThreeView({ view, objects, appRef, solarScale }) {
  useEffect(() => {
    const state = appRef.current;
    if (!state.scene) return;
    applyViewState(state, view);
    state.followObject = null;
    state.followCamera = false;
    state.lastFollowPos = null;
    state.controls.target.set(0, 0, 0);
    const solarCam = state.limits?.solarCam || LIMITS.real.solarCam;
    if (view === 'galaxy') state.camera.position.set(0, 220, 350);
    else if (view === 'local') state.camera.position.set(0, 35, 70);
    else state.camera.position.set(...solarCam);
    state.controls.update();
  }, [view, objects, appRef, solarScale]);
}