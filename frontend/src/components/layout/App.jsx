import { useCallback, useMemo, useState, useEffect } from 'react';
import { useObjectData } from '../../hooks/useObjectData.js';
import { useTimeEngine } from '../../hooks/useTimeEngine.js';
import { useThree } from '../../hooks/useThree.js';
import TimeControls from '../controls/TimeControls.jsx';
import ViewControls from '../controls/ViewControls.jsx';
import SearchBar from '../ui/SearchBar.jsx';
import ObjectList from '../ui/ObjectList.jsx';
import ScaleBadge from '../ui/ScaleBadge.jsx';
import Hint from '../ui/Hint.jsx';
import OverviewTab from '../tabs/OverviewTab.jsx';
import TelemetryTab from '../tabs/TelemetryTab.jsx';
import MissionsTab from '../tabs/MissionsTab.jsx';
import FactsTab from '../tabs/FactsTab.jsx';
import { formatLy, formatNum, formatPeriod } from '../../utils/formatUtils.js';
import { objectScale } from '../../bodies/utils/celestialUtils.js';

// Debounce hook for search input
function useDebounce(value, delay) {
  const [debouncedValue, setDebouncedValue] = useState(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

function App() {
  const {
    objects, selected, setSelected, query, setQuery,
    view, setView, follow, setFollow, loading,
    errorDetails, setErrorDetails, panelTab, setPanelTab,
    appRef, solarScale, setSolarScale,
  } = useObjectData();

  const { simDate, setSimDate, timeMultiplier, setTimeMultiplier, isPaused, setIsPaused } = useTimeEngine();

  const { mountRef } = useThree({
    objects, view, setView, selected, setSelected, follow, setFollow,
    appRef, simDate, setErrorDetails, solarScale,
  });

  // Debounce search query to avoid filtering on every keystroke
  const debouncedQuery = useDebounce(query, 300);

  // Binary v2 rows carry names but not descriptions/facts, so a non-empty
  // query is resolved by the compact `/api/search` endpoint. Results are just
  // ids; the rows themselves stay in `objects` (with colors and scene fields).
  const [serverSearch, setServerSearch] = useState({ query: '', ids: null });
  useEffect(() => {
    const q = debouncedQuery.trim();
    if (!q) {
      setServerSearch({ query: '', ids: null });
      return undefined;
    }
    let cancelled = false;
    const controller = new AbortController();
    fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal: controller.signal })
      .then((response) => (response.ok ? response.json() : Promise.reject(
        new Error(`search HTTP ${response.status}`),
      )))
      .then((rows) => {
        if (cancelled) return;
        setServerSearch({ query: q, ids: new Set(rows.map((row) => row.id)) });
      })
      .catch((err) => {
        if (cancelled || err.name === 'AbortError') return;
        // Keep the old client-side filter as a fallback for name/latin.
        console.warn('Server search failed, falling back to client filter:', err);
        setServerSearch({ query: q, ids: null });
      });
    return () => { cancelled = true; controller.abort(); };
  }, [debouncedQuery]);

  // Список пересчитывается только при смене debounced-запроса или масштаба.
  // useTimeEngine ререндерит App 10 раз в секунду — без debounce фильтр
  // срабатывал на каждом рендере.
  const filtered = useMemo(() => {
    const q = debouncedQuery.trim().toLowerCase();
    if (!q) return objects;
    // Only use a result set that belongs to the current query: a stale set
    // from the previous keystroke would briefly show the wrong rows.
    if (serverSearch.query === debouncedQuery.trim() && serverSearch.ids) {
      return objects.filter((o) => serverSearch.ids.has(o.id));
    }
    return objects.filter((o) => {
      // Fallback: binary rows have name/latin; solar JSON also has description.
      // facts/missions валидируются как список строк, но клиент не должен
      // падать, даже если придёт старый или битый каталог.
      const blob = [o.name, o.latin, o.description, o.constellation, o.spectral_type,
        ...(Array.isArray(o.facts) ? o.facts : [])].join(' ').toLowerCase();
      return blob.includes(q);
    });
  }, [objects, debouncedQuery, serverSearch]);

  const displayObjects = useMemo(
    () => filtered.filter((o) => objectScale(o) === view),
    [filtered, view],
  );

  const changeView = useCallback((nextView) => {
    if (nextView === view) return;
    setSelected(null);
    setFollow(false);
    setView(nextView);
  }, [view, setSelected, setFollow, setView]);

  const selectObject = useCallback((object) => {
    setView(objectScale(object));
    setSelected(object);
    setFollow(true);
    setPanelTab('overview');
  }, [setView, setSelected, setFollow, setPanelTab]);

  return (
    <div className="app">
      {errorDetails && (
        <div style={{
          position: 'fixed', top: '90px', left: '340px', right: '20px', zIndex: 99999,
          background: 'rgba(180, 20, 20, 0.9)', border: '2px solid #ff6666', borderRadius: '12px',
          padding: '20px', color: '#fff', fontFamily: 'monospace', fontSize: '13px', whiteSpace: 'pre-wrap'
        }}>
          <h3 style={{ margin: '0 0 10px 0', fontSize: '16px' }}>❌ Ошибка:</h3>
          {errorDetails}
        </div>
      )}

      <header className="topbar">
        <div className="brand">
          <div className="logo">✦</div>
          <div><b>ASTROVERSE</b><small>ORBITAL TIME EXPLORER</small></div>
        </div>
        <TimeControls
          setSimDate={setSimDate}
          isPaused={isPaused}
          setIsPaused={setIsPaused}
          timeMultiplier={timeMultiplier}
          setTimeMultiplier={setTimeMultiplier}
        />
        <div className="topmeta">
          <span className="liveDot" /> {objects.length} ТЕЛ
        </div>
      </header>

      <aside className="sidebar glass">
        <SearchBar query={query} setQuery={setQuery} />
        <ViewControls view={view} setView={changeView} solarScale={solarScale} setSolarScale={setSolarScale} />
        <ObjectList displayObjects={displayObjects} loading={loading} selected={selected} setSelected={selectObject} />
        <div className="controlBlock">
          <label className="followToggle">
            <input
              id="follow-toggle"
              name="follow"
              type="checkbox"
              checked={follow}
              onChange={(e) => setFollow(e.target.checked)}
            />
            <span>Следить за объектом</span>
          </label>
        </div>
      </aside>

      <main ref={mountRef} className="viewport" />

      <ScaleBadge simDate={simDate} />

      {selected && (
        <section className="infoPanel glass">
          <button className="close" onClick={() => {
            setSelected(null);
            setFollow(false);

          }}>×</button>

          <div className="panelHeader">
            <div className="eyebrow">{selected.kind.toUpperCase()}</div>
            <h1>{selected.name}</h1>
            {selected.latin && selected.latin !== selected.name && <div className="latin">{selected.latin}</div>}
          </div>

          <div className="panelTabs">
            <button className={panelTab === 'overview' ? 'tabBtn on' : 'tabBtn'} onClick={() => setPanelTab('overview')}>Обзор</button>
            <button className={panelTab === 'telemetry' ? 'tabBtn on' : 'tabBtn'} onClick={() => setPanelTab('telemetry')}>Телеметрия</button>
            {selected.missions && <button className={panelTab === 'missions' ? 'tabBtn on' : 'tabBtn'} onClick={() => setPanelTab('missions')}>Миссии</button>}
            <button className={panelTab === 'facts' ? 'tabBtn on' : 'tabBtn'} onClick={() => setPanelTab('facts')}>Факты</button>
          </div>

          <div className="panelBody">
            {panelTab === 'overview' && <OverviewTab selected={selected} />}
            {panelTab === 'telemetry' && <TelemetryTab selected={selected} formatNum={formatNum} formatLy={formatLy} formatPeriod={formatPeriod} />}
            {panelTab === 'missions' && selected.missions && <MissionsTab missions={selected.missions} />}
            {panelTab === 'facts' && <FactsTab facts={selected.facts} />}
          </div>

          {selected.source && <div className="source">Источник: {selected.source}</div>}
        </section>
      )}

      <Hint />
    </div>
  );
}

export default App;