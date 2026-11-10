import { useEffect, useState, useRef } from 'react';

import { PhysicalSectorManager } from './sectorManager.js';

export function useVerifiedFrame(simDate, neighborhood = null, anchor = 'earth', { continuous = false, generation = 0 } = {}) {
  const manager = useRef(null);
  if (!manager.current) manager.current = new PhysicalSectorManager();
  const milliseconds = simDate.getTime();
  const neighborhoodKey = JSON.stringify(neighborhood);
  const contextKey = JSON.stringify([neighborhoodKey, anchor, continuous, generation]);
  const [state, setState] = useState({ requested:null, frame:null, error:null });
  const [admitted, setAdmitted] = useState({ contextKey, milliseconds });
  const requestedMilliseconds = continuous && admitted.contextKey === contextKey ? admitted.milliseconds : milliseconds;
  useEffect(() => () => manager.current.cancel(), []);
  useEffect(() => { setAdmitted({contextKey, milliseconds}); }, [contextKey]);
  // One in-flight selection and one latest desired instant. Clock ticks do not
  // cancel useful work; explicit controls/context changes start a new generation.
  useEffect(() => {
    if (continuous && !state.permanent && state.contextKey === contextKey && state.requested === requestedMilliseconds
        && milliseconds !== requestedMilliseconds) setAdmitted({contextKey, milliseconds});
  }, [milliseconds, state, continuous, contextKey, requestedMilliseconds]);
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    // Explicit contexts hide the old frame during render above; release its
    // state reference as well instead of retaining it throughout a slow load.
    setState(previous => (!continuous || previous.contextKey !== contextKey) && (previous.frame || previous.error)
      ? {requested:null, frame:null, error:null} : previous);
    const load = async () => {
      const body = await manager.current.load({ milliseconds:requestedMilliseconds, neighborhood, anchor,
        signal:controller.signal, context:contextKey, retainPrevious:continuous });
      if (!cancelled) setState({ requested:requestedMilliseconds, contextKey, neighborhoodKey, anchor, frame:body, error:null });
    };
    load().catch(error => {
      if (!cancelled && error.name !== 'AbortError') setState({ requested: requestedMilliseconds, contextKey, neighborhoodKey, anchor,
        frame:null, error:error.message, permanent:!!error.permanent });
    });
    return () => { cancelled = true; controller.abort(); };
  }, [requestedMilliseconds, contextKey]);
  const interval = state.frame?.coordinates.utc_interval;
  const supportedTime = !interval || (milliseconds >= Date.parse(interval[0]) && milliseconds < Date.parse(interval[1]));
  const eligible = state.contextKey === contextKey && supportedTime
    && (continuous || state.requested === milliseconds);
  return eligible ? { ...state, lagMs:milliseconds-state.requested } : { frame:null, error:null, lagMs:0 };
}
