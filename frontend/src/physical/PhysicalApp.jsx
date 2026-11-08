import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTimeEngine } from '../hooks/useTimeEngine.js';
import TimeControls from '../components/controls/TimeControls.jsx';
import ObjectList from '../components/ui/ObjectList.jsx';
import PhysicalScene from './PhysicalScene.jsx';
import { useVerifiedFrame } from './useVerifiedFrame.js';
import { SectorStore } from '../data/sectorStore.js';


export default function PhysicalApp() {
  const [nowMode, setNowMode] = useState(true);
  const [timeGeneration, setTimeGeneration] = useState(0);
  const time = useTimeEngine({ nowMode });
  const [query, setQuery] = useState('');
  const [bodies, setBodies] = useState([]);
  const [registryRevision, setRegistryRevision] = useState(null);
  const [models, setModels] = useState([]);
  const [supportedTotal, setSupportedTotal] = useState(0);
  const [searchBodies, setSearchBodies] = useState([]);
  const [searchModels, setSearchModels] = useState([]);
  const verifiedIds = new Set(bodies.map(row => row.id));
  const supported = row => verifiedIds.has(row.id) || (row.verifiedRegistry && row.registryRevision === registryRevision);
  const [registryError, setRegistryError] = useState(null);
  const [rows, setRows] = useState([]);
  const [searchError, setSearchError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [card, setCard] = useState(null);
  const [cardError, setCardError] = useState(null);
  const [centerId, setCenterId] = useState('earth');
  const [overview, setOverview] = useState(false);
  const [focusVersion, setFocusVersion] = useState(0);
  const [sceneError, setSceneError] = useState(null);
  const [initializationError, setInitializationError] = useState(null);
  const [total, setTotal] = useState(null);
  const sceneRef = useRef(null);
  const store = useRef(null);
  if (!store.current) store.current = new SectorStore();
  const [neighborhood, setNeighborhood] = useState(null);
  const { frame, error } = useVerifiedFrame(time.simDate, neighborhood, centerId, {continuous:!time.isPaused, generation:timeGeneration});
  const lastRegistryRevision = useRef(null);
  if (frame?.registry_revision) lastRegistryRevision.current = frame.registry_revision;
  const positionRegistryRevision = lastRegistryRevision.current;
  const onSceneError = useCallback((message, phase = 'frame') => {
    if (phase === 'initialization') setInitializationError(message);
    else setSceneError(message);
  }, []);
  const setManualDate = useCallback(value => { setTimeGeneration(v=>v+1); setNowMode(false); time.setSimDate(value); }, [time.setSimDate]);
  const onNow = () => {
    setTimeGeneration(v=>v+1); setNowMode(true); time.setTimeMultiplier(1); time.setIsPaused(false); time.setSimDate(new Date());
  };

  useEffect(() => {
    if (positionRegistryRevision && positionRegistryRevision === registryRevision) return undefined;
    const controller = new AbortController();
    let cancelled = false;
    fetch('/api/sources/v1/objects?limit=128', { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error(`Реестр: HTTP ${response.status}`);
        const data = await response.json();
        if (data.version !== 'sources/1' || !Array.isArray(data.objects) || data.objects.length > 128)
          throw new Error('Некорректный реестр');
        if (cancelled) return;
        setRegistryRevision(data.revision);
        setBodies(data.objects.map(row=>({...row, verifiedRegistry:true, registryRevision:data.revision})));
        setModels(data.models || []); setSupportedTotal(data.total ?? data.objects.length);
        setRegistryError(null); setSearchBodies([]); setSearchModels([]);
      }).catch(error => { if (!cancelled && error.name !== 'AbortError') setRegistryError(error.message); });
    return () => { cancelled = true; controller.abort(); };
  }, [positionRegistryRevision]);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/health', { signal: controller.signal }).then(r => r.json()).then(data => setTotal(data.objects)).catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const q = query.trim();
    if (!q) { setRows(bodies); setSearchError(null); return undefined; }
    const controller = new AbortController();
    let cancelled = false;
    const timer = setTimeout(() => {
      Promise.all([fetch(`/api/search?q=${encodeURIComponent(q)}`, { signal: controller.signal })
        .then(async r => { if (!r.ok) throw new Error(`Поиск: HTTP ${r.status}`); return r.json(); }),
        fetch(`/api/sources/v1/objects?limit=128&q=${encodeURIComponent(q)}`, {signal:controller.signal})
          .then(async r => { if (!r.ok) throw new Error(`Реестр: HTTP ${r.status}`); return r.json(); })])
        .then(([catalog, registry]) => {
          if (registry.version !== 'sources/1' || !Array.isArray(registry.objects) || registry.objects.length > 128) throw new Error('Некорректный реестр');
          return {rows:[...registry.objects.map(row=>({...row,verifiedRegistry:true,registryRevision:registry.revision})), ...catalog.filter(row=>!registry.objects.some(body=>body.id===row.id))].slice(0,500), registry};
        })
        .then(data => { if (!cancelled) { setRows(data.rows); setSearchBodies(data.registry.objects); setSearchModels(data.registry.models || []); setSearchError(null); } })
        .catch(err => { if (!cancelled && err.name !== 'AbortError') { setRows([]); setSearchError(err.message); } });
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); controller.abort(); };
  }, [query, bodies]);

  useEffect(() => {
    if (!selected || supported(selected)) { setCard(null); setCardError(null); return undefined; }
    const controller = new AbortController();
    let cancelled = false;
    setCard(null); setCardError(null);
    store.current.object(selected.id, controller.signal)
      .then(result => { if (!cancelled) setCard(result); })
      .catch(err => { if (!cancelled && err.name !== 'AbortError') setCardError(err.message); });
    return () => { cancelled = true; controller.abort(); };
  }, [selected, registryRevision]);

  const select = row => {
    setSelected(row);
    if (supported(row)) { setCenterId(row.id); setOverview(false); setFocusVersion(value => value + 1); }
  };
  const position = frame?.objects.find(row => row.id === selected?.id && row.position);
  return <div className="app physicalApp">
    <header className="topbar">
      <div className="brand"><div className="logo">✦</div><div><b>ASTROVERSE</b><small>ПРОВЕРЕННЫЕ ПОЛОЖЕНИЯ</small></div></div>
      <TimeControls {...time} setSimDate={setManualDate} setTimeMultiplier={value=>{setTimeGeneration(v=>v+1);time.setTimeMultiplier(value);}} onNow={onNow} />
      <a href="?scene=legacy" className="legacyLink">Иллюстративный вид</a>
    </header>
    <aside className="sidebar glass">
      <div className="controlBlock"><b>{bodies.map(body => body.name).join(' · ')}</b><p>{models.map(model => model.source).join(' · ')} · геометрические центры</p>
        <p>В каталоге: {total ?? '…'}. Положения на дату подтверждены для {supportedTotal} тел.</p>
        <button className="viewBtn" onClick={() => setOverview(value => !value)}>{overview ? 'Окрестность тела' : 'Обзор системы'}</button>
        <p>Маркеры увеличены в пикселях. Расстояния линейные.</p>
      </div>
      <input className="physicalSearch" aria-label="Поиск по всему каталогу" value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск по всему каталогу…" />
      {registryError && <p role="alert">{registryError}</p>}
      {searchError && <p role="alert">{searchError}</p>}
      <ObjectList displayObjects={rows} selected={selected} setSelected={select} loading={false} />
      {query.trim() && <small>До 500 совпадений. Неподтверждённые тела доступны в карточках.</small>}
      <div className="controlBlock"><label>Дата UTC
        <input type="datetime-local" aria-label="Дата UTC" step="1" value={time.simDate.toISOString().slice(0,19)}
          onChange={e => { const date = new Date(e.target.value+'Z'); if (Number.isFinite(date.getTime())) { time.setIsPaused(true); setManualDate(date); } }} />
      </label><p>UTC: 2000-01-01 — 2026-12-31. Вне диапазона центры скрыты.</p></div>
    </aside>
    <PhysicalScene bodies={[...bodies, ...searchBodies]} frame={frame} centerId={centerId} overview={overview} focusVersion={focusVersion} onError={onSceneError} sceneRef={sceneRef} onNeighborhood={setNeighborhood} />
    <div className="physicalStatus glass" role="status">
      <div>{time.simDate.toISOString()} · {!time.isPaused && nowMode && time.timeMultiplier === 1 ? 'Сейчас' : 'Симуляция'}</div>
      {initializationError || sceneError || error ? <div role="alert">{initializationError || sceneError || error}</div>
        : <div>{frame ? (time.isPaused ? 'Положения вычислены на этот момент' : 'Положения вычислены на момент кадра') : 'Вычисление положений…'}</div>}
      {frame && !time.isPaused && <div>Кадр UTC: {frame.evaluated_at} · отставание от часов симуляции: {((time.simDate.getTime()-Date.parse(frame.evaluated_at))/1000).toFixed(3)} с</div>}
      <small>ICRF · барицентр Солнечной системы · км · TDB. Неподтверждённые положения не показаны.</small>
    </div>
    {selected && <section className="infoPanel glass">
      <button className="close" onClick={() => setSelected(null)}>×</button>
      <div className="panelHeader"><h1>{selected.name}</h1></div>
      <div className="panelBody">
        <p>{position ? (time.isPaused ? 'Положение на выбранный момент вычислено' : 'Положение вычислено на момент кадра') : supported(selected)
          ? 'Положение не загружено для выбранной области или даты' : 'Положение на выбранный момент неизвестно'}</p>
        {position && !time.isPaused && <p>Момент положения UTC: {frame.evaluated_at}</p>}
        {position && <p>ICRF XYZ, км: {position.position.map(v => v.toFixed(3)).join(', ')}</p>}
        {card && <><p>{card.object.description}</p><p>Координаты каталога: {card.coordinates.status}. Эпоха: {card.coordinates.source_epoch ?? 'неизвестна'}.</p></>}
        {cardError && <p role="alert">{cardError}</p>}
        <p>Абсолютная погрешность отдельного вектора не предоставлена. Метаданные модели и временные границы опубликованы в реестре.</p>
      </div>
      <div className="source">Источник положения: {supported(selected) ? ([...models,...searchModels].find(model=>model.id===selected.model_id)?.source || 'Источник в реестре') : 'нет подтверждённой эфемериды'}</div>
    </section>}
  </div>;
}
