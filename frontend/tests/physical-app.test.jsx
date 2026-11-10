import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import PhysicalApp from '../src/physical/PhysicalApp.jsx';

const registry = {version:'sources/1', objects:[['sun','Солнце'],['mercury','Меркурий'],['venus','Венера'],['earth','Земля'],['moon','Луна']].map(([id,name])=>({id,name,kind:'planet',color:'#ffffff'}))};

const mocks=vi.hoisted(()=>({ time:null, positions:{frame:null,error:null}, scene:null, card:vi.fn() }));
vi.mock('../src/hooks/useTimeEngine.js',()=>({useTimeEngine:()=>mocks.time}));
vi.mock('../src/physical/useVerifiedFrame.js',()=>({useVerifiedFrame:()=>mocks.positions}));
vi.mock('../src/physical/PhysicalScene.jsx',()=>({default:props=>{mocks.scene=props;return <main className="viewport"/>;}}));
vi.mock('../src/data/sectorStore.js',()=>({SectorStore:class { object(...args){return mocks.card(...args);} }}));

beforeEach(()=>{
  mocks.time={simDate:new Date('2026-11-06T00:00:00Z'),timeMultiplier:1,isPaused:false,
    setSimDate:vi.fn(),setTimeMultiplier:vi.fn(),setIsPaused:vi.fn()};
  mocks.positions={frame:{objects:[{id:'earth',position:[1,2,3]}]},error:null};
  mocks.card.mockReset().mockResolvedValue({object:{id:'remote',description:'Full card'},coordinates:{status:'unverified',source_epoch:null}});
  vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,status:200,json:async()=>path==='/api/health'?{objects:3471}:path.startsWith('/api/sources/')?registry:[{id:'remote',name:'Remote',kind:'star'}]})));
});

describe('physical experience',()=>{
  it('shows the active source UTC interval from registry metadata',async()=>{
    const data={...registry,models:[{id:'de440',utc_interval:['2000-01-01T00:00:00Z','2027-06-28T00:00:00Z']}],
      objects:registry.objects.map(row=>({...row,model_id:'de440'}))};
    vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>path.startsWith('/api/sources/')?data:{objects:3471}})));
    render(<PhysicalApp/>);
    await screen.findByText(/2000-01-01 ≤ дата < 2027-06-28/);
    expect(screen.queryByText(/2026-12-31/)).toBe(null);
  });
  it('loads no full catalog, offers a far view and only focuses verified centers',async()=>{
    render(<PhysicalApp/>);
    await screen.findByText(/В каталоге: 3471/);
    expect(fetch.mock.calls.map(c=>c[0])).toEqual(['/api/sources/v1/objects?limit=128','/api/health']);
    expect(mocks.scene.centerId).toBe('earth');
    fireEvent.click(screen.getByText('Обзор системы'));expect(mocks.scene.overview).toBe(true);
    fireEvent.click(screen.getByText('Луна'));expect(mocks.scene.centerId).toBe('moon');expect(mocks.scene.overview).toBe(false);
    const focusVersion=mocks.scene.focusVersion; fireEvent.click(screen.getAllByText('Луна')[0]);
    expect(mocks.scene.focusVersion).toBe(focusVersion+1);
    expect(mocks.card).not.toHaveBeenCalled();expect(screen.getByText('Положение не загружено для выбранной области или даты')).toBeTruthy();
    fireEvent.click(screen.getByText('×'));expect(screen.queryByText('Положение не загружено для выбранной области или даты')).toBe(null);
    fireEvent.click(screen.getByText('Земля'));expect(screen.getByText(/ICRF XYZ, км/)).toBeTruthy();
    fireEvent.click(screen.getByText('Сейчас'));expect(mocks.time.setSimDate).toHaveBeenCalledWith(expect.any(Date));
    expect(mocks.time.setTimeMultiplier).toHaveBeenCalledWith(1);expect(mocks.time.setIsPaused).toHaveBeenCalledWith(false);
    fireEvent.click(screen.getByText('+1 день'));expect(mocks.time.setSimDate).toHaveBeenCalledWith(expect.any(Function));
    fireEvent.change(screen.getByLabelText('Дата UTC'),{target:{value:'2020-01-01T12:34'}});
    expect(mocks.time.setIsPaused).toHaveBeenCalledWith(true);
    expect(mocks.time.setSimDate).toHaveBeenCalledWith(new Date('2020-01-01T12:34Z'));
    fireEvent.change(screen.getByLabelText('Дата UTC'),{target:{value:''}});
    expect(screen.getByText('Иллюстративный вид').getAttribute('href')).toBe('?scene=legacy');
  });
  it('lists five supported bodies and focuses the new planets with computed positions', async()=>{
    mocks.positions={frame:{objects:[{id:'mercury',position:[1,2,3]},{id:'venus',position:[4,5,6]}]},error:null};
    render(<PhysicalApp/>);
    await screen.findByText(/В каталоге: 3471/);
    expect(document.querySelectorAll('.objectRow')).toHaveLength(5);
    expect(screen.getByText(/подтверждены для 5 тел/)).toBeTruthy();
    for (const [name,id] of [['Меркурий','mercury'],['Венера','venus']]) {
      fireEvent.click(screen.getAllByText(name)[0]);
      expect(mocks.scene.centerId).toBe(id);expect(mocks.scene.overview).toBe(false);
      expect(screen.getByText('Положение вычислено на момент кадра')).toBeTruthy();
      expect(screen.getByText(/ICRF XYZ, км/)).toBeTruthy();
    }
    expect(mocks.card).not.toHaveBeenCalled();
  });
  it('finds unloaded cards through sectors, keeps them unknown and cancels old selections',async()=>{
    render(<PhysicalApp/>);
    fireEvent.change(screen.getByLabelText('Поиск по всему каталогу'),{target:{value:'remote'}});
    fireEvent.click(await screen.findByText('Remote'));
    expect(mocks.scene.centerId).toBe('earth');
    await screen.findByText('Full card');expect(mocks.card).toHaveBeenCalledWith('remote',expect.any(AbortSignal));
    expect(screen.getByText(/Координаты каталога: unverified/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Поиск по всему каталогу'),{target:{value:''}});
    await screen.findByText('Солнце');
    fireEvent.click(screen.getByText('Солнце'));expect(mocks.scene.centerId).toBe('sun');
    expect(mocks.card.mock.calls[0][1].aborted).toBe(true);
  });
  it('shows source epoch when provided, and explicit HTTP, card and position errors',async()=>{
    mocks.positions={frame:null,error:'unsupported time'};
    const view=render(<PhysicalApp/>);expect(screen.getByText('unsupported time')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Поиск по всему каталогу'),{target:{value:'remote'}});
    fireEvent.click(await screen.findByText('Remote'));
    mocks.card.mockRejectedValueOnce(new Error('sector limit'));
    fireEvent.click(screen.getByText('×'));fireEvent.click(screen.getByText('Remote'));
    await screen.findByText('sector limit');
    act(()=>mocks.scene.onError('lost WebGL'));expect(screen.getByText('lost WebGL')).toBeTruthy();
    view.unmount();
    vi.stubGlobal('fetch',vi.fn(async path=>({ok:false,status:503,json:async()=>({objects:1})})));
    render(<PhysicalApp/>);fireEvent.change(screen.getByLabelText('Поиск по всему каталогу'),{target:{value:'fail'}});
    await screen.findByText('Поиск: HTTP 503');
  });
  it('ignores late cards and aborted search responses',async()=>{
    let resolve;
    mocks.card.mockImplementationOnce(()=>new Promise(done=>{resolve=done;}));
    const view=render(<PhysicalApp/>);
    fireEvent.change(screen.getByLabelText('Поиск по всему каталогу'),{target:{value:'remote'}});
    fireEvent.click(await screen.findByText('Remote'));
    fireEvent.click(screen.getByText('×'));
    await act(async()=>resolve({object:{description:'late'},coordinates:{status:'unknown',source_epoch:'epoch'}}));
    expect(screen.queryByText('late')).toBe(null);
    view.unmount();
    vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new DOMException('aborted','AbortError')));
    render(<PhysicalApp/>);fireEvent.change(screen.getByLabelText('Поиск по всему каталогу'),{target:{value:'cancel'}});
    await act(async()=>new Promise(done=>setTimeout(done,350)));
    expect(screen.queryAllByRole('alert')).toHaveLength(0);
  });
});

it('uses synthetic registry membership and marker metadata beyond five without a body-specific branch', async()=>{
  const synthetic={version:'sources/1',total:300,next_offset:128,models:[{id:'test',source:'Synthetic test provider'}],
    objects:Array.from({length:9},(_,i)=>({id:`synthetic-${i}`,name:`Synthetic ${i}`,kind:'planet',color:'#aa0000',model_id:'test'}))};
  vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>path.startsWith('/api/sources/')?synthetic:{objects:3471}})));
  render(<PhysicalApp/>);
  fireEvent.click(await screen.findByText('Synthetic 8'));
  expect(document.querySelector('.controlBlock b').textContent).toContain('ещё 4');
  expect(mocks.scene.centerId).toBe('synthetic-8');
  expect(mocks.scene.bodies.find(row=>row.id==='synthetic-8').color).toBe('#aa0000');
  expect(mocks.card).not.toHaveBeenCalled();
  expect(screen.getByText(/подтверждены для 300 тел/)).toBeTruthy();
  expect(screen.getByText('Источник положения: Synthetic test provider')).toBeTruthy();
});

it('reports malformed registry pages without inventing default bodies',async()=>{
  vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>path.startsWith('/api/sources/')?{version:'sources/1',objects:Array(129).fill({})}:{objects:3471}})));
  render(<PhysicalApp/>);
  await screen.findByText('Некорректный реестр');
  expect(document.querySelectorAll('.objectRow')).toHaveLength(0);
});

it('refreshes registry composition on a new position revision while preserving selection and scene props',async()=>{
  let registry={version:'sources/1',revision:'r1',models:[],objects:[{id:'earth',name:'Test Earth',kind:'planet',model_id:'test',color:'#ffffff'}]};
  vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,json:async()=>path.startsWith('/api/sources/')?registry:{objects:3471}})));
  mocks.positions={frame:{registry_revision:'r1',objects:[]},error:null};
  const view=render(<PhysicalApp/>);
  fireEvent.click(await screen.findByText('Test Earth'));
  const focus=mocks.scene.focusVersion;
  registry={...registry,revision:'r2',objects:[...registry.objects,{id:'synthetic-added',name:'Synthetic Added',kind:'planet',model_id:'test',color:'#aa00ff'}]};
  mocks.positions={frame:{registry_revision:'r2',objects:[]},error:null};
  view.rerender(<PhysicalApp/>);
  await screen.findByText('Synthetic Added');
  expect(mocks.scene.bodies).toHaveLength(2);
  expect(mocks.scene.centerId).toBe('earth');expect(mocks.scene.focusVersion).toBe(focus);
  expect(fetch.mock.calls.filter(([url])=>url.startsWith('/api/sources/'))).toHaveLength(2);
  expect(mocks.card).not.toHaveBeenCalled();
  mocks.positions={frame:null,error:null}; view.rerender(<PhysicalApp/>);
  await act(async()=>{});
  expect(fetch.mock.calls.filter(([url])=>url.startsWith('/api/sources/'))).toHaveLength(2);
});

it('clears recovered frame errors without hiding an initialization failure',async()=>{
  render(<PhysicalApp/>);await screen.findByText(/В каталоге: 3471/);
  act(()=>mocks.scene.onError('temporary frame error','frame'));
  expect(screen.getByText('temporary frame error')).toBeTruthy();
  act(()=>mocks.scene.onError(null,'frame'));
  expect(screen.queryByText('temporary frame error')).toBe(null);
  act(()=>mocks.scene.onError('no WebGL','initialization'));
  act(()=>mocks.scene.onError(null,'frame'));
  expect(screen.getByText('no WebGL')).toBeTruthy();
  act(()=>mocks.scene.onError(null,'initialization'));
  expect(screen.queryByText('no WebGL')).toBe(null);
  expect(screen.getByText('Положения вычислены на момент кадра')).toBeTruthy();
});

it('picks located IDs beyond the metadata page and refocuses known bodies at either LOD',async()=>{
 mocks.positions.frame.objects.push({id:'synthetic-tail',position:[4,5,6]});
 render(<PhysicalApp/>);await screen.findByText(/В каталоге: 3471/);
 act(()=>mocks.scene.onPick('synthetic-tail'));
 expect(screen.getByRole('heading',{name:'synthetic-tail'})).toBeTruthy();
 expect(mocks.scene.centerId).toBe('synthetic-tail');
 act(()=>mocks.scene.onPick('earth'));expect(mocks.scene.centerId).toBe('earth');
 act(()=>mocks.scene.onPick('missing'));expect(mocks.scene.centerId).toBe('earth');
});

it('refocuses a picked registry search result beyond the first metadata page',async()=>{
 const remote={id:'verified-remote',name:'Remote verified',model_id:'de440'};
 vi.stubGlobal('fetch',vi.fn(async path=>({ok:true,status:200,json:async()=>path==='/api/health'?{objects:3471}:path.includes('/api/sources/')?path.includes('&q=')?{...registry,revision:'r1',objects:[remote]}:{...registry,revision:'r1'}:[]})));
 mocks.positions.frame.objects.push({id:remote.id,position:[4,5,6]});
 render(<PhysicalApp/>);await screen.findByText(/В каталоге: 3471/);
 fireEvent.change(screen.getByLabelText('Поиск по всему каталогу'),{target:{value:'verified-remote'}});
 await screen.findByText('Remote verified');
 act(()=>mocks.scene.onPick(remote.id));
 expect(mocks.scene.centerId).toBe(remote.id);
});
it('keeps scene metadata stable across clock-only renders',async()=>{
 const view=render(<PhysicalApp/>);await screen.findByText(/В каталоге: 3471/);
 const bodies=mocks.scene.bodies;
 mocks.time={...mocks.time,simDate:new Date('2026-11-06T00:00:01Z')};
 view.rerender(<PhysicalApp/>);expect(mocks.scene.bodies).toBe(bodies);
});
