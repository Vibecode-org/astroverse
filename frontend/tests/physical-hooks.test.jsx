import React from 'react';
import { render, renderHook, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import * as THREE from 'three';
import { useVerifiedFrame } from '../src/physical/useVerifiedFrame.js';
import PhysicalScene from '../src/physical/PhysicalScene.jsx';

const stages = vi.hoisted(() => ({ latest: null, fail: false, builds: 0 }));
vi.mock('../src/scene/stage.js', () => ({ createStage: el => {
  if (stages.fail) throw new Error('no WebGL');
  stages.builds++;
  const state = { scene: new THREE.Scene(), camera: new THREE.PerspectiveCamera(),
    renderer: { render: vi.fn(), dispose: vi.fn(), setSize: vi.fn(), domElement: document.createElement('canvas') },
    controls: { target: new THREE.Vector3(), update: vi.fn(), dispose: vi.fn() } };
  state.camera.position.set(0,8,12);
  el.appendChild(state.renderer.domElement); stages.latest=state; return state;
} }));
const at = '2026-11-06T00:00:00.000Z';
const frame = { version:'positions/1', revision:'r1', sector:'solar:verified', evaluated_at: at, jd_tdb:2461350,
  coordinates: { representation:'simulation_position',unit:'km',reference_system:'ICRF',origin:'solar_system_barycenter',corrections:'NONE',time_scale:'TDB',revision:'r1' },
  objects: [{ id:'earth',position:[1e8,0,0],status:'computed' },{ id:'moon',position:[1e8+300000,0,0],status:'computed' }] };
function reply(body,ok=true,status=200) { return {ok,status,json:async()=>body}; }

describe('verified time requests', () => {
  it('hides stale positions immediately, ignores cancelled requests and displays explicit failures', async () => {
    let pending;
    const fetcher=vi.fn().mockResolvedValueOnce(reply(frame)).mockImplementationOnce(()=>new Promise(resolve=>{pending=resolve;}))
      .mockResolvedValueOnce(reply({...frame,evaluated_at:'2026-11-06T00:00:02.000Z'}));
    vi.stubGlobal('fetch',fetcher);
    const {result,rerender,unmount}=renderHook(({date})=>useVerifiedFrame(date),{initialProps:{date:new Date(at)}});
    await waitFor(()=>expect(result.current.frame).toEqual(frame));
    rerender({date:new Date('2026-11-06T00:00:01Z')}); expect(result.current.frame).toBe(null);
    rerender({date:new Date('2026-11-06T00:00:02Z')});
    await waitFor(()=>expect(result.current.frame?.evaluated_at).toContain('00:00:02'));
    await act(async()=>pending(reply({...frame,evaluated_at:'2026-11-06T00:00:01Z'})));
    expect(result.current.frame.evaluated_at).toContain('00:00:02');
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true); unmount();
  });
  it('reports invalid dates, contract mismatches, HTTP and network errors without old coordinates', async () => {
    for (const [answer,message] of [[reply({...frame,evaluated_at:'2000-01-01T00:00:00Z'}),'другому моменту'],
      [reply({version:'v2'}),'контракт'], [reply({detail:{message:'outside interval'}},false,422),'outside interval'],
      [reply({},false,503),'HTTP 503'],
      [{ok:false,status:502,json:async()=>{throw new Error('HTML gateway response');}},'HTTP 502'],
      [{ok:true,status:200,json:async()=>{throw new Error('bad JSON');}},'Некорректный ответ']]) {
      vi.stubGlobal('fetch',vi.fn().mockResolvedValue(answer));
      const hook=renderHook(()=>useVerifiedFrame(new Date(at)));
      await waitFor(()=>expect(hook.result.current.error).toContain(message));
      expect(hook.result.current.frame).toBe(null);hook.unmount();
    }
    vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));
    const hook=renderHook(()=>useVerifiedFrame(new Date(at)));
    await waitFor(()=>expect(hook.result.current.error).toBe('offline'));hook.unmount();
    vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new DOMException('cancelled','AbortError')));
    const aborted=renderHook(()=>useVerifiedFrame(new Date(at)));
    await act(async()=>{}); expect(aborted.result.current.error).toBe(null); aborted.unmount();
  });
});

describe('physical scene lifetime', () => {
  it('keeps one renderer through time, residency and origin changes, then disposes it', () => {
    vi.stubGlobal('requestAnimationFrame',vi.fn(()=>42)); vi.stubGlobal('cancelAnimationFrame',vi.fn());
    const sceneRef={current:null}, onError=vi.fn(); stages.builds=0;
    const view=render(<PhysicalScene frame={frame} centerId="earth" overview={false} onError={onError} sceneRef={sceneRef}/>);
    expect(stages.builds).toBe(1); expect(sceneRef.current.frames).toBe(1);
    const layer=sceneRef.current.layer;
    view.rerender(<PhysicalScene frame={frame} centerId="moon" overview onError={onError} sceneRef={sceneRef}/>);
    expect(stages.builds).toBe(1);expect(sceneRef.current.layer).toBe(layer);
    const renderer=stages.latest.renderer;
    for(const count of [9,129,1,129]) {
      const synthetic={...frame,objects:Array.from({length:count},(_,i)=>({id:`synthetic-${i}`,status:'computed',position:[i,0,0]}))};
      view.rerender(<PhysicalScene frame={synthetic} bodies={synthetic.objects.map(row=>({...row,color:'#ffffff'}))} centerId="synthetic-0" overview onError={onError} sceneRef={sceneRef}/>);
      expect(stages.latest.renderer).toBe(renderer);expect(stages.builds).toBe(1);
    }
    stages.latest.camera.position.set(999,888,777);
    view.rerender(<PhysicalScene frame={frame} centerId="moon" overview focusVersion={1} onError={onError} sceneRef={sceneRef}/>);
    expect(stages.latest.camera.position.toArray()).toEqual([0,1800,2400]);
    act(()=>window.dispatchEvent(new Event('resize')));expect(stages.latest.renderer.setSize).toHaveBeenCalled();
    view.rerender(<PhysicalScene frame={{version:'v2'}} centerId="earth" onError={onError} sceneRef={sceneRef}/>);
    expect(onError).toHaveBeenCalled();expect(layer.inspect().rows).toHaveLength(0);
    view.unmount();expect(sceneRef.current).toBe(null);expect(stages.latest.renderer.dispose).toHaveBeenCalledOnce();
    expect(stages.latest.controls.dispose).toHaveBeenCalledOnce();expect(cancelAnimationFrame).toHaveBeenCalledWith(42);
  });
  it('reports initialization errors and cleans up partial resources', () => {
    stages.fail=true;
    const onError=vi.fn(), sceneRef={current:null};
    const view=render(<PhysicalScene frame={null} onError={onError} sceneRef={sceneRef}/>);
    expect(onError).toHaveBeenCalledWith('no WebGL','initialization');view.unmount(); stages.fail=false;
  });
});

it('loads only a returned verified sector and evicts it in an empty camera neighborhood', async () => {
  const near={offset:[0,0,0],radius:2e6};
  const fetcher=vi.fn().mockResolvedValueOnce(reply({...frame,objects:[],sectors:[{id:'solar:verified',revision:frame.revision}]}))
    .mockResolvedValueOnce(reply(frame)).mockResolvedValueOnce(reply({...frame,objects:[],sectors:[]}));
  vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(({area})=>useVerifiedFrame(new Date(at),area,'earth'),{initialProps:{area:near}});
  await waitFor(()=>expect(hook.result.current.frame?.objects).toHaveLength(2));
  expect(fetcher.mock.calls[0][0]).toContain('/nearby?'); expect(fetcher.mock.calls[0][0]).toContain('anchor=earth');
  expect(fetcher.mock.calls[1][0]).toContain('/sectors/solar%3Averified?');
  hook.rerender({area:{offset:[1e12,0,0],radius:1}});
  expect(hook.result.current.frame).toBe(null);
  await waitFor(()=>expect(hook.result.current.frame?.objects).toHaveLength(0));
  expect(fetcher).toHaveBeenCalledTimes(3);hook.unmount();
});

it('publishes camera neighborhood changes without rebuilding the renderer', () => {
  vi.stubGlobal('requestAnimationFrame',vi.fn(()=>21));vi.stubGlobal('cancelAnimationFrame',vi.fn());
  const onNeighborhood=vi.fn(),sceneRef={current:null},onError=vi.fn();
  const view=render(<PhysicalScene frame={frame} centerId="earth" overview={false} onError={onError} sceneRef={sceneRef} onNeighborhood={onNeighborhood}/>);
  expect(onNeighborhood).toHaveBeenCalledOnce();
  const [{offset,radius}]=onNeighborhood.mock.calls[0];
  expect(offset).toEqual([0,-1200000,800000]);expect(radius).toBeGreaterThan(2e6);
  const tick=requestAnimationFrame.mock.calls[0][0];
  act(()=>tick());expect(onNeighborhood).toHaveBeenCalledOnce();
  stages.latest.camera.position.set(100000000,0,0);act(()=>tick());
  expect(onNeighborhood).toHaveBeenCalledTimes(2);
  view.unmount();
});

const near={offset:[0,0,0],radius:2e6};
const revised=revision=>({...frame,revision,coordinates:{...frame.coordinates,revision}});
const manifest=value=>({...value,objects:[],sectors:[{id:'solar:verified',revision:value.revision}]});

it.each(['different-body-revision','HTTP409'])('rediscovers and pins the whole selection after %s',async failure=>{
  const next=revised('r2');
  const fetcher=vi.fn().mockResolvedValueOnce(reply(manifest(frame)))
    .mockResolvedValueOnce(failure==='HTTP409'?reply({detail:{code:'position_revision_changed'}},false,409):reply(next))
    .mockResolvedValueOnce(reply(manifest(next))).mockResolvedValueOnce(reply(next));
  vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(()=>useVerifiedFrame(new Date(at),near));
  await waitFor(()=>expect(hook.result.current.frame?.revision).toBe('r2'));
  expect(fetcher).toHaveBeenCalledTimes(4);
  expect(fetcher.mock.calls[1][0]).toContain('revision=r1');
  expect(fetcher.mock.calls[2][0]).toContain('/nearby?');
  expect(fetcher.mock.calls[3][0]).toContain('revision=r2');
  expect(hook.result.current.error).toBe(null);hook.unmount();
});

it('limits revision-conflict recovery to one retry and leaves no stale positions',async()=>{
  const fetcher=vi.fn().mockResolvedValueOnce(reply(manifest(frame)))
    .mockResolvedValueOnce(reply({},false,409)).mockResolvedValueOnce(reply(manifest(frame)))
    .mockResolvedValueOnce(reply({},false,409));
  vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(()=>useVerifiedFrame(new Date(at),near));
  await waitFor(()=>expect(hook.result.current.error).toContain('Ревизия'));
  expect(hook.result.current.frame).toBe(null);expect(fetcher).toHaveBeenCalledTimes(4);hook.unmount();
});

it('clears a frame error only after a valid frame, preserving renderer and initialization errors',()=>{
  vi.stubGlobal('requestAnimationFrame',vi.fn(()=>1));vi.stubGlobal('cancelAnimationFrame',vi.fn());
  const onError=vi.fn(),sceneRef={current:null};stages.builds=0;
  const view=render(<PhysicalScene frame={frame} centerId="earth" onError={onError} sceneRef={sceneRef}/>);
  const renderer=stages.latest.renderer;
  view.rerender(<PhysicalScene frame={{version:'v2'}} centerId="earth" onError={onError} sceneRef={sceneRef}/>);
  expect(onError.mock.lastCall).toEqual([expect.stringContaining('контракт'),'frame']);
  view.rerender(<PhysicalScene frame={null} centerId="earth" onError={onError} sceneRef={sceneRef}/>);
  expect(onError.mock.lastCall[0]).not.toBe(null);
  view.rerender(<PhysicalScene frame={frame} centerId="earth" onError={onError} sceneRef={sceneRef}/>);
  expect(onError.mock.lastCall).toEqual([null,'frame']);
  expect(stages.latest.renderer).toBe(renderer);expect(stages.builds).toBe(1);view.unmount();
});

it.each(['sector','tdb','registry'])('does not publish a response with a mismatched %s binding',async field=>{
  const bad={...frame, sector:field==='sector'?'other':frame.sector,
    jd_tdb:field==='tdb'?frame.jd_tdb+1:frame.jd_tdb,
    registry_revision:field==='registry'?'other':undefined};
  const fetcher=vi.fn().mockResolvedValueOnce(reply(manifest(frame))).mockResolvedValueOnce(reply(bad))
    .mockResolvedValueOnce(reply(manifest(frame))).mockResolvedValueOnce(reply(bad));
  vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(()=>useVerifiedFrame(new Date(at),near));
  await waitFor(()=>expect(hook.result.current.error).toBeTruthy());
  expect(hook.result.current.frame).toBe(null);
  expect(fetcher).toHaveBeenCalledTimes(field==='registry'?4:2);hook.unmount();
});

it('retries an inconsistent manifest before any sector read',async()=>{
  const bad=manifest(frame);bad.sectors[0].revision='old';
  const fetcher=vi.fn().mockResolvedValueOnce(reply(bad)).mockResolvedValueOnce(reply(manifest(frame))).mockResolvedValueOnce(reply(frame));
  vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(()=>useVerifiedFrame(new Date(at),near));
  await waitFor(()=>expect(hook.result.current.frame).toEqual(frame));
  expect(fetcher).toHaveBeenCalledTimes(3);expect(fetcher.mock.calls[1][0]).toContain('/nearby?');hook.unmount();
});

it('does not start a sector read for a cancelled manifest',async()=>{
  let finishOld;
  const next={...frame,evaluated_at:'2026-11-06T00:00:01.000Z'};
  const fetcher=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finishOld=resolve;}))
    .mockResolvedValueOnce(reply(manifest(next))).mockResolvedValueOnce(reply(next));
  vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(({date})=>useVerifiedFrame(date,near),{initialProps:{date:new Date(at)}});
  hook.rerender({date:new Date(next.evaluated_at)});
  await waitFor(()=>expect(hook.result.current.frame).toEqual(next));
  await act(async()=>finishOld(reply(manifest(frame))));
  expect(fetcher).toHaveBeenCalledTimes(3);expect(hook.result.current.frame).toEqual(next);hook.unmount();
});

it.each([
  value=>({...value,revision:''}),
  value=>({...value,revision:'x'.repeat(257)}),
  value=>({...value,coordinates:{...value.coordinates,revision:'wrong'}}),
  value=>({...value,sectors:null}),
  value=>({...value,sectors:[value.sectors[0],value.sectors[0]]}),
  value=>({...value,sectors:[{id:'',revision:value.revision}]}),
])('rejects malformed revision/manifest metadata without retrying',async corrupt=>{
  const fetcher=vi.fn().mockResolvedValue(reply(corrupt(manifest(frame))));vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(()=>useVerifiedFrame(new Date(at),near));
  await waitFor(()=>expect(hook.result.current.error).toBeTruthy());
  expect(hook.result.current.frame).toBe(null);expect(fetcher).toHaveBeenCalledOnce();hook.unmount();
});

it('coalesces 100ms clock ticks behind delayed responses instead of starving frames',async()=>{
  vi.useFakeTimers();let active=0,maxActive=0;
  const fetcher=vi.fn(url=>new Promise(resolve=>{
    active++;maxActive=Math.max(maxActive,active);
    setTimeout(()=>{active--;resolve(reply({...frame,evaluated_at:new URL(url,'http://test').searchParams.get('at')}));},250);
  }));vi.stubGlobal('fetch',fetcher);
  const start=Date.parse(at);
  const hook=renderHook(({ms,generation=0})=>useVerifiedFrame(new Date(ms),null,'earth',{continuous:true,generation}),{initialProps:{ms:start}});
  let accepted=0;
  for(let i=1;i<=15;i++) {
    await act(async()=>{await vi.advanceTimersByTimeAsync(100);});
    hook.rerender({ms:start+i*100});
    if(hook.result.current.frame) {
      accepted++;
      expect(Date.parse(hook.result.current.frame.evaluated_at)).toBeLessThanOrEqual(start+i*100);
      expect(hook.result.current.lagMs).toBe(start+i*100-Date.parse(hook.result.current.frame.evaluated_at));
    }
  }
  expect(accepted).toBeGreaterThan(8);expect(maxActive).toBe(1);expect(fetcher.mock.calls.length).toBeLessThan(8);
  hook.rerender({ms:start+86400000,generation:1});expect(hook.result.current.frame).toBe(null);
  await act(async()=>{await vi.advanceTimersByTimeAsync(300);});
  expect(hook.result.current.frame?.evaluated_at).toBe(new Date(start+86400000).toISOString());hook.unmount();
});

it('immediately hides a completed continuous frame on pause, anchor change or unsupported time',async()=>{
  const supported={...frame,coordinates:{...frame.coordinates,utc_interval:['2000-01-01T00:00:00Z','2027-01-01T00:00:00Z']}};
  vi.stubGlobal('fetch',vi.fn().mockResolvedValueOnce(reply(supported)).mockImplementation(()=>new Promise(()=>{})));
  const hook=renderHook(({date,continuous,anchor='earth'})=>useVerifiedFrame(date,null,anchor,{continuous}),{initialProps:{date:new Date(at),continuous:true}});
  await waitFor(()=>expect(hook.result.current.frame).toBeTruthy());
  hook.rerender({date:new Date('2027-01-01T00:00:00Z'),continuous:true});expect(hook.result.current.frame).toBe(null);
  hook.rerender({date:new Date(at),continuous:false});expect(hook.result.current.frame).toBe(null);
  hook.rerender({date:new Date(at),continuous:true,anchor:'moon'});expect(hook.result.current.frame).toBe(null);hook.unmount();
});

it('finishes both delayed manifest/sector legs during continuous jitter and cancels explicit jumps',async()=>{
  vi.useFakeTimers();let active=0,maxActive=0;const dates=[];
  const delays=[250,400,150,300];let request=0;
  vi.stubGlobal('fetch',vi.fn((url,{signal})=>new Promise((resolve,reject)=>{
    active++;maxActive=Math.max(maxActive,active);
    const params=new URL(url,'http://test').searchParams,date=params.get('at');dates.push(date);
    const value={...frame,evaluated_at:date};
    let done=false;
    const timer=setTimeout(()=>{if(done)return;done=true;active--;resolve(reply(url.includes('/nearby?')?manifest(value):value));},delays[request++%delays.length]);
    signal.addEventListener('abort',()=>{if(done)return;done=true;clearTimeout(timer);active--;reject(new DOMException('cancelled','AbortError'));},{once:true});
  })));
  const start=Date.parse(at);
  const hook=renderHook(({ms,generation=0})=>useVerifiedFrame(new Date(ms),near,'earth',{continuous:true,generation}),{initialProps:{ms:start}});
  let frames=0;
  for(let i=1;i<=30;i++){
    await act(async()=>{await vi.advanceTimersByTimeAsync(100);});hook.rerender({ms:start+i*100});
    if(hook.result.current.frame)frames++;
  }
  expect(frames).toBeGreaterThan(15);expect(maxActive).toBe(1);expect(request).toBeLessThan(15);
  hook.rerender({ms:start-86400000,generation:1});expect(hook.result.current.frame).toBe(null);
  await act(async()=>{await vi.advanceTimersByTimeAsync(800);});
  expect(hook.result.current.frame.evaluated_at).toBe(new Date(start-86400000).toISOString());
  hook.unmount();expect(active).toBe(0);
});
