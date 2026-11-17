import { act, renderHook, waitFor } from '@testing-library/react';
import { it, expect, vi } from 'vitest';
import { PhysicalSectorManager } from '../src/physical/sectorManager.js';
import { useVerifiedFrame } from '../src/physical/useVerifiedFrame.js';

const start=Date.parse('2026-11-06T00:00:00Z');
const area={offset:[0,0,0],origin:[1e8,0,0],radius:2e6};
const reply=(body,status=200)=>({ok:status===200,status,json:async()=>body});
function envelope(ms=start,revision='r1') {
  return {version:'positions/1',revision,registry_revision:'registry',
    evaluated_at:new Date(ms).toISOString(),jd_tdb:2461350+(ms-start)/86400000,
    coordinates:{representation:'simulation_position',unit:'km',reference_system:'ICRF',
      origin:'solar_system_barycenter',time_scale:'TDB',corrections:'NONE',revision},objects:[]};
}
function payload(url,revision='r1',count=1) {
  const parsed=new URL(url,'http://test'),ms=Date.parse(parsed.searchParams.get('at'));
  const base=envelope(ms,revision);
  if(parsed.pathname.endsWith('/nearby'))return {...base,sectors:[{id:'temporal:0',revision,object_count:count}]};
  return {...base,sector:'temporal:0',objects:Array.from({length:count},(_,i)=>({
    id:'synthetic-'+i,status:'computed',source:'synthetic',position:[1e8+i*1000,(ms-start)/1000,0]}))};
}

it('keeps a conservative candidate outside the query radius at its requested-time center',async()=>{
  const fetcher=vi.fn(async url=>reply(payload(url)));
  const manager=new PhysicalSectorManager({fetcher});
  const frame=await manager.load({milliseconds:start+5000,neighborhood:{...area,radius:0}});
  expect(frame.objects[0].position).toEqual([1e8,5,0]);
  expect(frame.evaluated_at).toBe(new Date(start+5000).toISOString());
  const query=new URL(fetcher.mock.calls[0][0],'http://test').searchParams;
  expect(query.get('radius')).toBe('0');expect(query.get('ox')).toBe('100000000');
  expect(manager.inspect()).toMatchObject({selections:1,published:1,residentObjects:1});
});

it.each(['time','area'])('discards a late %s selection and drains all residency on cancellation',async kind=>{
  let finish;
  const fetcher=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}))
    .mockImplementation(async url=>reply(payload(url)));
  const manager=new PhysicalSectorManager({fetcher});
  const old=manager.load({milliseconds:start,neighborhood:area}).catch(error=>error);
  const next=await manager.load({milliseconds:kind==='time'?start-5000:start,
    neighborhood:kind==='area'?{...area,offset:[1e9,0,0]}:area});
  expect((await old).name).toBe('AbortError');
  finish(reply(payload(fetcher.mock.calls[0][0])));await Promise.resolve();await Promise.resolve();
  expect(next.objects[0].position[1]).toBe(kind==='time'?-5:0);
  expect(manager.inspect()).toMatchObject({selections:2,published:1,cancellations:1,
    cancelledRequests:1,staleResponses:1,residentObjects:1,active:0,pending:0,queue:0});
  manager.cancel();expect(manager.inspect()).toMatchObject({objects:0,decoded:0,serialized:0});
  expect(manager.inspect().cancellations).toBe(1); // Eviction alone is not cancelled work.
});

it('restarts temporal discovery on revision change and never publishes the discarded candidate set',async()=>{
  let revision='r1',conflict=true;
  const fetcher=vi.fn(async url=>{
    if(url.includes('/sectors/')&&conflict){conflict=false;revision='r2';return reply({},409);}
    return reply(payload(url,revision));
  });
  const manager=new PhysicalSectorManager({fetcher});
  const frame=await manager.load({milliseconds:start,neighborhood:area});
  expect(frame.revision).toBe('r2');expect(frame.coordinates.revision).toBe('r2');
  expect(fetcher.mock.calls[1][0]).toContain('revision=r1');
  expect(fetcher.mock.calls[3][0]).toContain('revision=r2');
  expect(manager.inspect()).toMatchObject({conflicts:1,published:1,residentObjects:1,pending:0});
});

it('pins a separate temporal publication and restarts discovery when that publication changes',async()=>{
  let temporalRevision='index1',changed=false;
  const fetcher=vi.fn(async url=>{
    const value=payload(url);
    if(url.includes('/sectors/')&&!changed){changed=true;temporalRevision='index2';}
    return reply({...value,temporal_revision:temporalRevision});
  });
  const manager=new PhysicalSectorManager({fetcher});
  expect((await manager.load({milliseconds:start,neighborhood:area})).temporal_revision).toBe('index2');
  expect(fetcher.mock.calls[1][0]).toContain('temporal_revision=index1');
  expect(fetcher.mock.calls[3][0]).toContain('temporal_revision=index2');
  expect(manager.inspect()).toMatchObject({conflicts:1,published:1});
});

it.each(['',null,1,'x'.repeat(257)])('rejects malformed temporal publication binding %s before sector work',async temporal_revision=>{
  const fetcher=vi.fn(async url=>reply({...payload(url),temporal_revision}));
  const manager=new PhysicalSectorManager({fetcher});
  await expect(manager.load({milliseconds:start,neighborhood:area})).rejects.toThrow('ревизия временного индекса');
  expect(fetcher).toHaveBeenCalledOnce();expect(manager.inspect().objects).toBe(0);
});

it('fails density overflow before sector work and releases the previously accepted frame',async()=>{
  let dense=false;
  const fetcher=vi.fn(async url=>dense?reply({detail:{message:'temporal density budget'}},413):reply(payload(url)));
  const manager=new PhysicalSectorManager({fetcher});
  await manager.load({milliseconds:start,neighborhood:area,context:'Now'});dense=true;
  await expect(manager.load({milliseconds:start+1000,neighborhood:area,context:'Now',retainPrevious:true}))
    .rejects.toMatchObject({permanent:true,message:'temporal density budget'});
  expect(fetcher).toHaveBeenCalledTimes(3);
  expect(manager.inspect()).toMatchObject({objects:0,decoded:0,serialized:0,pending:0,active:0,published:1});
});

it('admits at most two 2048-member temporal frames across repeated replacements',async()=>{
  const fetcher=vi.fn(async url=>{
    const value=payload(url);const revision=value.revision;
    if(url.includes('/nearby?'))return reply({...value,sectors:Array.from({length:16},(_,i)=>({id:'temporal:'+i,revision,object_count:128}))});
    const sector=decodeURIComponent(new URL(url,'http://test').pathname.split('/sectors/')[1]);
    return reply({...value,sector,objects:Array.from({length:128},(_,i)=>({
      id:sector+':'+i,status:'computed',position:[i,Number(sector.split(':')[1]),0]}))});
  });
  const manager=new PhysicalSectorManager({fetcher});
  for(let i=0;i<4;i++) {
    expect((await manager.load({milliseconds:start+i*1000,neighborhood:area,context:'Now',retainPrevious:true})).objects).toHaveLength(2048);
    expect(manager.inspect()).toMatchObject({residentObjects:2048,objects:2048,pending:0,queue:0,active:0});
  }
  expect(manager.inspect().peakObjects).toBe(4096);
  expect(manager.inspect().peakActive).toBeLessThanOrEqual(4);
  manager.cancel();expect(manager.inspect().objects).toBe(0);
});

it('coalesces desired ticks, then cancels reverse and pause generations and disposes in-flight work',async()=>{
  vi.useFakeTimers();let active=0,peak=0;
  const fetcher=vi.fn((url,{signal})=>new Promise((resolve,reject)=>{
    active++;peak=Math.max(peak,active);let done=false;
    const timer=setTimeout(()=>{done=true;active--;resolve(reply(payload(url)));},250);
    signal.addEventListener('abort',()=>{if(done)return;done=true;clearTimeout(timer);active--;reject(new DOMException('cancelled','AbortError'));},{once:true});
  }));vi.stubGlobal('fetch',fetcher);
  const hook=renderHook(({ms,continuous=true,generation=0})=>useVerifiedFrame(new Date(ms),area,'earth',{continuous,generation}),
    {initialProps:{ms:start}});
  for(let i=1;i<=8;i++) {
    await act(async()=>vi.advanceTimersByTimeAsync(100));
    hook.rerender({ms:start+i*100});
  }
  expect(hook.result.current.frame).toBeTruthy();
  expect(hook.result.current.metrics.coalescedTicks).toBeGreaterThan(4);
  hook.rerender({ms:start-5000,generation:1});expect(hook.result.current.frame).toBe(null);
  await act(async()=>vi.advanceTimersByTimeAsync(500));
  expect(hook.result.current.frame.objects[0].position[1]).toBe(-5);
  hook.rerender({ms:start-6000,continuous:false,generation:2});expect(hook.result.current.frame).toBe(null);
  await act(async()=>vi.advanceTimersByTimeAsync(500));
  expect(hook.result.current.frame.evaluated_at).toBe(new Date(start-6000).toISOString());
  hook.rerender({ms:start-7000,continuous:false,generation:3});
  hook.unmount();await act(async()=>vi.advanceTimersByTimeAsync(1000));
  expect(active).toBe(0);expect(peak).toBe(1);
});

it('reloads after a disposed consumer without retaining its previous manager frame',async()=>{
  vi.stubGlobal('fetch',vi.fn(async url=>reply(payload(url))));
  const first=renderHook(()=>useVerifiedFrame(new Date(start),area));
  await waitFor(()=>expect(first.result.current.frame?.objects).toHaveLength(1));first.unmount();
  const next=renderHook(()=>useVerifiedFrame(new Date(start+1000),area));
  expect(next.result.current.frame).toBe(null);
  await waitFor(()=>expect(next.result.current.frame?.objects[0].position[1]).toBe(1));
  expect(next.result.current.metrics).toMatchObject({selections:1,published:1,cancellations:0});next.unmount();
});
