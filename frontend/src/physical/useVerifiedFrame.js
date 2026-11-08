import { useEffect, useState } from 'react';
import { verifiedRows } from './coordinates.js';

class PositionRevisionChanged extends Error {
  constructor() { super('Ревизия положений изменилась; повторите запрос'); }
}

export function useVerifiedFrame(simDate, neighborhood = null, anchor = 'earth', { continuous = false, generation = 0 } = {}) {
  const milliseconds = simDate.getTime();
  const neighborhoodKey = JSON.stringify(neighborhood);
  const contextKey = JSON.stringify([neighborhoodKey, anchor, continuous, generation]);
  const [state, setState] = useState({ requested:null, frame:null, error:null });
  const [admitted, setAdmitted] = useState({ contextKey, milliseconds });
  const requestedMilliseconds = continuous && admitted.contextKey === contextKey ? admitted.milliseconds : milliseconds;
  useEffect(() => { setAdmitted({contextKey, milliseconds}); }, [contextKey]);
  // One in-flight selection and one latest desired instant. Clock ticks do not
  // cancel useful work; explicit controls/context changes start a new generation.
  useEffect(() => {
    if (continuous && state.contextKey === contextKey && state.requested === requestedMilliseconds
        && milliseconds !== requestedMilliseconds) setAdmitted({contextKey, milliseconds});
  }, [milliseconds, state, continuous, contextKey, requestedMilliseconds]);
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const params = new URLSearchParams({ at: new Date(requestedMilliseconds).toISOString() });
    if (neighborhood) {
      params.set('anchor', anchor);
      ['dx','dy','dz'].forEach((key,a)=>params.set(key, String(neighborhood.offset[a])));
      params.set('radius', String(neighborhood.radius));
    }
    const get = async (url, expectedRevision = null) => {
      if (cancelled) throw new DOMException('cancelled', 'AbortError');
      const response = await fetch(url, { signal: controller.signal });
      const body = await response.json().catch(() => null);
      if (response.status === 409) throw new PositionRevisionChanged();
      if (!response.ok) throw new Error(body?.detail?.message || `Эфемериды: HTTP ${response.status}`);
      if (!body) throw new Error('Некорректный ответ сервера эфемерид');
      verifiedRows(body);
      if (typeof body.revision !== 'string' || !body.revision || body.revision.length > 256
          || body.coordinates.revision !== body.revision) throw new Error('Некорректная ревизия положений');
      if (Date.parse(body.evaluated_at) !== requestedMilliseconds) throw new Error('Эфемерида относится к другому моменту');
      if (expectedRevision !== null && body.revision !== expectedRevision) throw new PositionRevisionChanged();
      return body;
    };
    const root = '/api/positions/v1/';
    const load = async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          const manifest = await get(root+(neighborhood ? 'nearby' : 'sectors/solar:verified')+'?'+params);
          let body = manifest;
          if (neighborhood) {
            // This loader deliberately supports one sector until the 3.3 manager.
            if (!Array.isArray(manifest.sectors) || manifest.sectors.length > 1) throw new Error('Некорректный manifest положений');
            if (manifest.sectors.length) {
              const sector = manifest.sectors[0];
              if (typeof sector.id !== 'string' || !sector.id || sector.id.length > 512) throw new Error('Некорректный ID сектора');
              if (sector.revision !== manifest.revision) throw new PositionRevisionChanged();
              const query = new URLSearchParams({ at:new Date(requestedMilliseconds).toISOString(), revision:manifest.revision });
              body = await get(root+'sectors/'+encodeURIComponent(sector.id)+'?'+query, manifest.revision);
              if (body.sector !== sector.id || body.jd_tdb !== manifest.jd_tdb) throw new Error('Несогласованный сектор или момент положений');
              if (body.registry_revision !== manifest.registry_revision) throw new PositionRevisionChanged();
            }
          }
          if (!cancelled) setState({ requested: requestedMilliseconds, contextKey, neighborhoodKey, anchor, frame: body, error: null });
          return;
        } catch (error) {
          // Retry the whole selection once, never combine revisions or loop forever.
          if (error instanceof PositionRevisionChanged && attempt === 0 && !cancelled) continue;
          throw error;
        }
      }
    };
    load().catch(error => {
      if (!cancelled && error.name !== 'AbortError') setState({ requested: requestedMilliseconds, contextKey, neighborhoodKey, anchor, frame: null, error: error.message });
    });
    return () => { cancelled = true; controller.abort(); };
  }, [requestedMilliseconds, contextKey]);
  const interval = state.frame?.coordinates.utc_interval;
  const supportedTime = !interval || (milliseconds >= Date.parse(interval[0]) && milliseconds < Date.parse(interval[1]));
  const eligible = state.contextKey === contextKey && supportedTime
    && (continuous || state.requested === milliseconds);
  return eligible ? { ...state, lagMs:milliseconds-state.requested } : { frame:null, error:null, lagMs:0 };
}
