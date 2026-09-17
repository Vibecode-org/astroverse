import React, { useMemo } from 'react';
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

const VIEWS = [
  { id: 'solar', label: 'Солнечная система', icon: '☼' },
  { id: 'local', label: 'Окрестности Солнца', icon: '✦' },
  { id: 'galaxy', label: 'Млечный Путь', icon: '◌' },
];

function App() {
  const {
    objects, setObjects, selected, setSelected, query, setQuery,
    view, setView, follow, setFollow, loading, setLoading,
    errorDetails, setErrorDetails, panelTab, setPanelTab,
    appRef,
  } = useObjectData();

  const { simDate, setSimDate, timeMultiplier, setTimeMultiplier, isPaused, setIsPaused } = useTimeEngine();

  const { mountRef } = useThree({
    objects, view, setView, selected, setSelected, follow, setFollow,
    appRef, simDate, setSimDate, isPaused, timeMultiplier, setErrorDetails,
  });

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return objects.filter((o) => {
      if (!q) return true;
      const blob = [o.name, o.latin, o.description, o.constellation, o.spectral_type, ...(o.facts || [])].join(' ').toLowerCase();
      return blob.includes(q);
    });
  }, [objects, query]);

  const displayObjects = filtered.filter((o) => objectScale(o) === view);

  const changeView = (nextView) => {
    if (nextView === view) return;
    setSelected(null);
    setFollow(false);
    setView(nextView);
  };

  const selectObject = (object) => {
    setView(objectScale(object));
    setSelected(object);
    setFollow(true);
    setPanelTab('overview');
  };

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
          simDate={simDate}
          setSimDate={setSimDate}
          isPaused={isPaused}
          setIsPaused={setIsPaused}
          timeMultiplier={timeMultiplier}
          setTimeMultiplier={setTimeMultiplier}
        />
        <div className="topmeta">
          <span className="liveDot" /> NASA JPL LIVE <span className="sep">/</span> {objects.length} ТЕЛ
        </div>
      </header>

      <aside className="sidebar glass">
        <SearchBar query={query} setQuery={setQuery} />
        <ViewControls view={view} setView={changeView} />
        <ObjectList displayObjects={displayObjects} loading={loading} selected={selected} setSelected={selectObject} />
        <div className="controlBlock">
          <label className="followToggle">
            <input
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