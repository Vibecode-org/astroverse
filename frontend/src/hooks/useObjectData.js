import { useState, useEffect, useRef } from 'react';
import { readBinaryCatalog } from '../data/readBinaryCatalog.js';

/** Load the catalog.
 *
 * Hybrid data path (Phase 2.4):
 *   - the Solar System stays on JSON: `buildSolarLayout` needs au, radius_km,
 *     moon_distance, parent, rings and textures, and there are only ~515
 *     objects;
 *   - local/galaxy objects come from the v2 binary SoA catalog, which carries
 *     render positions, ids/names, scale, physical radii, au and period.
 *
 * The binary reader reconstructs the same object shape the JSON path used, so
 * App, ObjectList, buildDeepSky, objectScale and formatUtils are unchanged.
 * If the binary request or parse fails, the hook falls back to the full JSON
 * catalog and logs a warning instead of leaving a blank canvas.
 */
export function useObjectData() {
  const [objects, setObjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const [view, setView] = useState('solar');
  const [follow, setFollow] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errorDetails, setErrorDetails] = useState(null);
  const [panelTab, setPanelTab] = useState('overview');
  const [catalogInfo, setCatalogInfo] = useState(null);
  // По умолчанию компактный масштаб: планеты видны сразу, без «пустого»
  // стартового экрана. Реальный масштаб включается кнопкой и показывает
  // истинные пропорции расстояний.
  const [solarScale, setSolarScale] = useState('compact');
  const appRef = useRef({});

  useEffect(() => {
    let cancelled = false;
    const started = performance.now();
    performance.mark('astroverse:catalog-load-start');

    const finish = () => {
      performance.mark('astroverse:catalog-load-end');
      performance.measure(
        'astroverse:catalog-load',
        'astroverse:catalog-load-start',
        'astroverse:catalog-load-end',
      );
    };

    const load = async () => {
      try {
        // Solar JSON is small and carries the metadata buildSolarLayout needs.
        const solarResponse = await fetch('/api/objects?scale=solar');
        if (!solarResponse.ok) {
          throw new Error(`solar catalog HTTP ${solarResponse.status}`);
        }
        const solar = await solarResponse.json();

        // v2 binary is explicit (`?format=v2`); v1 stays the default for older
        // clients. `scale=solar` is intentionally not applied here: the binary
        // payload is one request and solar rows are dropped on the client.
        const binaryResponse = await fetch('/api/objects?format=v2');
        if (!binaryResponse.ok) {
          throw new Error(`binary catalog HTTP ${binaryResponse.status}`);
        }
        const buffer = await binaryResponse.arrayBuffer();

        performance.mark('astroverse:binary-parse-start');
        const parsed = readBinaryCatalog(buffer);
        performance.mark('astroverse:binary-parse-end');
        performance.measure(
          'astroverse:binary-parse',
          'astroverse:binary-parse-start',
          'astroverse:binary-parse-end',
        );

        if (parsed.version !== 2) {
          throw new Error(`unexpected binary catalog version ${parsed.version}`);
        }

        // The binary contains every scale; solar is replaced by the JSON rows
        // (they have textures/rings/moon fields that the binary omits).
        const binaryObjects = parsed.objects.filter((obj) => obj.scale !== 'solar');
        const merged = [...solar, ...binaryObjects];

        if (cancelled) return;
        setObjects(merged);
        setCatalogInfo({
          source: 'binary-v2',
          version: parsed.version,
          total: merged.length,
          solarCount: solar.length,
          binaryCount: binaryObjects.length,
          binaryBytes: buffer.byteLength,
          loadMs: performance.now() - started,
          parseMs: performance.getEntriesByName('astroverse:binary-parse').pop()?.duration ?? null,
        });
        setLoading(false);
        finish();
      } catch (err) {
        console.warn('Binary catalog unavailable, falling back to JSON:', err);
        try {
          const response = await fetch('/api/objects');
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          const data = await response.json();
          if (cancelled) return;
          setObjects(data);
          setCatalogInfo({ source: 'json-fallback', total: data.length });
          setLoading(false);
          finish();
        } catch (fallbackError) {
          console.error('API Fetch Error:', fallbackError);
          if (cancelled) return;
          setErrorDetails('Ошибка API: ' + fallbackError.message);
          setLoading(false);
          finish();
        }
      }
    };

    load();
    return () => { cancelled = true; };
  }, []);

  // Full metadata (description/facts/telemetry) is not part of the compact
  // binary payload. Solar rows already have it; for local/galaxy objects fetch
  // the card once on selection. The object list and scene keep working with
  // the binary row while the request is in flight.
  useEffect(() => {
    if (!selected || selected.description !== undefined || selected._detailsLoaded) {
      return undefined;
    }
    let cancelled = false;
    fetch(`/api/objects/${encodeURIComponent(selected.id)}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((details) => {
        if (cancelled || !details) return;
        setSelected((previous) => (
          previous && previous.id === details.id
            ? { ...previous, ...details, _detailsLoaded: true }
            : previous
        ));
      })
      .catch((err) => {
        console.warn(`Failed to load details for ${selected.id}:`, err);
      });
    return () => { cancelled = true; };
  }, [selected, setSelected]);

  return {
    objects, setObjects, selected, setSelected, query, setQuery,
    view, setView, follow, setFollow, loading, setLoading,
    errorDetails, setErrorDetails, panelTab, setPanelTab,
    appRef, solarScale, setSolarScale, catalogInfo,
  };
}
