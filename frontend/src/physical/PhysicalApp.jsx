import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTimeEngine } from '../hooks/useTimeEngine.js';
import TimeControls from '../components/controls/TimeControls.jsx';
import ObjectList from '../components/ui/ObjectList.jsx';
import PhysicalScene from './PhysicalScene.jsx';
import { useVerifiedFrame } from './useVerifiedFrame.js';
import { SectorStore } from '../data/sectorStore.js';


export default function PhysicalApp() {
  const [presentedFrame,setPresentedFrame]=useState(null);
  const [profile, setProfile] = useState(null);
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
  const sceneBodies = useMemo(() => [...bodies, ...searchBodies], [bodies, searchBodies]);
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
  const [flying,setFlying]=useState(false);
  const [flightStatus,setFlightStatus]=useState({speed:100000,held:0});
  const [sceneError, setSceneError] = useState(null);
  const [initializationError, setInitializationError] = useState(null);
  const [total, setTotal] = useState(null);
  const sceneRef = useRef(null);
  const store = useRef(null);
  if (!store.current) store.current = new SectorStore();
  const [neighborhood, setNeighborhood] = useState(null);
  const { frame, error } = useVerifiedFrame(time.simDate, neighborhood, centerId, {continuous:!time.isPaused, generation:timeGeneration, profile, presentedFrame});
  const displayFrame=frame?.objects?.length>4096?presentedFrame:frame;
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
        setProfile(data.profile || null);
        if(data.profile === 'synthetic-s100k') {setCenterId('synthetic-origin');setOverview(true);}
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
        .then(data => { if (!cancelled) { setRows(data.rows); setSearchBodies(data.registry.objects.map(row=>({...row,verifiedRegistry:true,registryRevision:data.registry.revision}))); setSearchModels(data.registry.models || []); setSearchError(null); } })
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
    if (!flying && supported(row)) { setCenterId(row.id); setOverview(false); setFocusVersion(value => value + 1); }
  };
  const refocus=()=>{
    setFlying(false);setCenterId(selected && supported(selected)?selected.id:centerId);
    setOverview(false);setFocusVersion(value=>value+1);
  };
  const changeFlightSpeed=factor=>{
    sceneRef.current?.flight.changeSpeed(factor);
    if(sceneRef.current)setFlightStatus(sceneRef.current.flight.inspect());
  };
  const pick = id => {
    const known = [...bodies, ...searchBodies].find(body => body.id === id);
    const located = frame?.objects.find(body => body.id === id && body.position);
    if (known) select(known);
    else if (located) select({ ...located, name: id, verifiedRegistry: true, registryRevision });
  };
  const position = displayFrame?.objects.find(row => row.id === selected?.id && row.position);
  const activeBody = [...bodies,...searchBodies].find(row=>row.id===centerId);
  const utcInterval = [...models,...searchModels].find(model=>model.id===activeBody?.model_id)?.utc_interval;
  return <div className="app physicalApp">
    <header className="topbar">
      <div className="brand"><div className="logo">✦</div><div><b>ASTROVERSE</b><small>{profile === 'synthetic-s100k' ? 'SYNTHETIC S-100k · НЕ НАБЛЮДЕНИЯ' : 'ПРОВЕРЕННЫЕ ПОЛОЖЕНИЯ'}</small></div></div>
      <TimeControls {...time} setSimDate={setManualDate} setTimeMultiplier={value=>{setTimeGeneration(v=>v+1);time.setTimeMultiplier(value);}} onNow={onNow} />
      <a href="?scene=legacy" className="legacyLink">Иллюстративный вид</a>
    </header>
    <aside className="sidebar glass">
      <div className="controlBlock"><b>{bodies.slice(0,5).map(body => body.name).join(' · ')}{bodies.length > 5 && ` · ещё ${bodies.length-5}`}</b><p>{models.map(model => model.source).join(' · ')} · геометрические центры</p>
        <p>В каталоге: {total ?? '…'}. В реестре положений: {supportedTotal} тел.</p>
        <button className="viewBtn" onClick={() => {setFlying(false);if(profile==='synthetic-s100k')setCenterId('synthetic-origin');setOverview(value => !value);}}>{overview ? 'Окрестность тела' : 'Обзор системы'}</button>
        <p>L0: точки; L1: кольцевые маркеры рядом и при выборе. Размеры графические, не радиусы тел. Расстояния линейные.</p>
      </div>
      <input className="physicalSearch" aria-label="Поиск по всему каталогу" value={query} onChange={e => setQuery(e.target.value)} placeholder="Поиск по всему каталогу…" />
      {registryError && <p role="alert">{registryError}</p>}
      {searchError && <p role="alert">{searchError}</p>}
      <ObjectList displayObjects={rows} selected={selected} setSelected={select} loading={false} />
      {query.trim() && <small>До 500 совпадений. Неподтверждённые тела доступны в карточках.</small>}
      <div className="controlBlock"><label>Дата UTC
        <input type="datetime-local" aria-label="Дата UTC" step="1" value={time.simDate.toISOString().slice(0,19)}
          onChange={e => { const date = new Date(e.target.value+'Z'); if (Number.isFinite(date.getTime())) { time.setIsPaused(true); setManualDate(date); } }} />
      </label><p>{utcInterval ? `UTC: ${utcInterval[0].slice(0,10)} ≤ дата < ${utcInterval[1].slice(0,10)}.`
        : 'Поддержанный UTC-интервал опубликован в реестре.'} Вне диапазона центры скрыты.</p></div>
    </aside>
      <div className="controlBlock navigationHelp glass">
        <button className="viewBtn" onClick={()=>setFlying(value=>!value)}>{flying?'Завершить полёт':'Свободный полёт'}</button>
        <button className="viewBtn" onClick={refocus}>Наблюдать {selected && supported(selected)?selected.name:'опорное тело'}</button>
        {flying ? <>
          <p>W/S вперёд/назад · A/D вбок · R/F вверх/вниз. Стрелки: поворот · Q/E: крен. Мышь: поворот с перетаскиванием.</p>
          <p>+/−: скорость · Пробел: стоп. Движение пока клавиша зажата; отпускание останавливает. Нажмите на сцену для управления.</p>
          <p>Скорость хода: {flightStatus.speed.toLocaleString('ru-RU')} км/с (реальное время).</p>
          <button onClick={()=>changeFlightSpeed(.5)} aria-label="Уменьшить скорость полёта">−</button>
          <button onClick={()=>changeFlightSpeed(2)} aria-label="Увеличить скорость полёта">+</button>
          <button onClick={()=>sceneRef.current?.flight.stop()}>Стоп</button>
          <p>Выбор открывает карточку без перемещения. «Наблюдать» возвращает к телу и следует за ним во времени.</p>
        </> : <p>Мышь: орбита и масштаб. Свободный полёт: перемещение и вращение по трём осям. «Наблюдать» возвращает к телу.</p>}
      </div>
    <PhysicalScene bodies={sceneBodies} frame={frame} centerId={centerId} overview={overview} focusVersion={focusVersion} onError={onSceneError} sceneRef={sceneRef} onNeighborhood={setNeighborhood} selectedId={selected?.id} onPick={pick} flying={flying} onFlightStatus={setFlightStatus} onPresented={setPresentedFrame} />
    <div className="physicalStatus glass" role="status">
      <div>{time.simDate.toISOString()} · {!time.isPaused && nowMode && time.timeMultiplier === 1 ? 'Сейчас' : 'Симуляция'}</div>
      {initializationError || sceneError || error ? <div role="alert">{initializationError || sceneError || error}</div>
        : <div>{displayFrame ? (time.isPaused ? 'Положения вычислены на этот момент' : 'Положения вычислены на момент кадра') : 'Вычисление положений…'}</div>}
      {displayFrame && !time.isPaused && <div>Кадр UTC: {displayFrame.evaluated_at} · отставание от часов симуляции: {((time.simDate.getTime()-Date.parse(displayFrame.evaluated_at))/1000).toFixed(3)} с</div>}
      <small>ICRF · барицентр Солнечной системы · км · TDB. Неподтверждённые положения не показаны.</small>
    </div>
    {selected && <section className="infoPanel glass">
      <button className="close" onClick={() => setSelected(null)}>×</button>
      <div className="panelHeader"><h1>{selected.name}</h1></div>
      <div className="panelBody">
        <p>{position ? (time.isPaused ? 'Положение на выбранный момент вычислено' : 'Положение вычислено на момент кадра') : supported(selected)
          ? 'Положение не загружено для выбранной области или даты' : 'Положение на выбранный момент неизвестно'}</p>
        {position && !time.isPaused && <p>Момент положения UTC: {displayFrame.evaluated_at}</p>}
        {position && <p>ICRF XYZ, км: {position.position.map(v => v.toFixed(3)).join(', ')}</p>}
        {card && <><p>{card.object.description}</p><p>Координаты каталога: {card.coordinates.status}. Эпоха: {card.coordinates.source_epoch ?? 'неизвестна'}.</p></>}
        {cardError && <p role="alert">{cardError}</p>}
        <p>Абсолютная погрешность отдельного вектора не предоставлена. Метаданные модели и временные границы опубликованы в реестре.</p>
      </div>
      <div className="source">Источник положения: {supported(selected) ? ([...models,...searchModels].find(model=>model.id===selected.model_id)?.source || 'Источник в реестре') : 'нет подтверждённой эфемериды'}</div>
    </section>}
  </div>;
}
