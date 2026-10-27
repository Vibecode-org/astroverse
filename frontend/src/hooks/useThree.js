/** Main Three.js hook: composes scene, view, follow, and time sub-hooks. */

import { useCallback } from 'react';
import { useThreeScene } from './useThreeScene.js';
import { useThreeView } from './useThreeView.js';
import { useThreeFollow } from './useThreeFollow.js';
import { useThreeTime } from './useThreeTime.js';
import { applyViewState } from '../scene/viewState.js';

/** Mounts the Three.js scene and keeps it in sync with the UI state.
 *
 * The scene itself is built exactly once per (objects, solarScale) pair and
 * then mutated in place; everything else — view switching, selection, follow —
 * is handled by the sub-hooks below, which only touch the shared `appRef`
 * state object. That split is what keeps a 10 Hz time engine from rebuilding
 * 3471 meshes every tick.
 */
export function useThree({
  objects,
  view,
  setView,
  selected,
  setSelected,
  follow,
  setFollow,
  appRef,
  simDate,
  setErrorDetails,
  solarScale,
}) {
  // Callback for picking — stable reference so useThreeScene effect doesn't re-run
  const onPick = useCallback((obj, scale) => {
    setView(scale);
    setSelected(obj);
    setFollow(true);
  }, [setView, setSelected, setFollow]);

  // Scene initialization (renderer, objects, animation loop)
  const { mountRef } = useThreeScene({
    objects,
    solarScale,
    appRef,
    setErrorDetails,
    onPick,
    simDate,
  });

  // View switching (solar/local/galaxy)
  useThreeView({ view, objects, appRef, solarScale });

  // Time engine sync (10 Hz)
  useThreeTime({ simDate, objects, appRef });

  // Object selection & camera follow
  useThreeFollow({ selected, follow, setView, setFollow, appRef, objects });

  return { mountRef };
}