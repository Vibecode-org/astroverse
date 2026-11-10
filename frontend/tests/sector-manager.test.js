import { it, expect, vi } from 'vitest';
import { PhysicalSectorManager } from '../src/physical/sectorManager.js';
const milliseconds=Date.parse('2026-11-06T00:00:00Z');
const coordinates={representation:'simulation_position',unit:'km',reference_system:'ICRF',origin:'solar_system_barycenter',time_scale:'TDB',corrections:'NONE',revision:'r'};
const frame=(id='a')=>({version:'positions/1',revision:'r',registry_revision:'reg',evaluated_at:new Date(milliseconds).toISOString(),jd_tdb:2461350,coordinates,sector:id,
 objects:[{id,position:[1,2,3],status:'computed'}],hierarchy:{version:'physical-hierarchy/1',revision:'r',evaluated_at:new Date(milliseconds).toISOString(),jd_tdb:2461350,
 reference_system:'ICRF',origin:'solar_system_barycenter',unit:'km',time_scale:'TDB',sectors:[{id,origin_km:[0,0,0]}],systems:[{id:id+'sys',sector_id:id,offset_km:[0,0,0]}],bodies:[{id,system_id:id+'sys',offset_km:[1,2,3]}]}});
const manifest=(ids=['a','b','c'])=>{const f=frame();delete f.hierarchy;return {...f,objects:[],sectors:ids.map(id=>({id,revision:'r'}))};};
const reply=(body,status=200)=>({ok:status===200,status,json:async()=>body});
it('creates diagnostic UUIDs when randomUUID is unavailable on an HTTP LAN origin',()=>{
 const original=globalThis.crypto;
 vi.stubGlobal('crypto',{getRandomValues:original.getRandomValues.bind(original)});
 const first=new PhysicalSectorManager().inspect().clientId,second=new PhysicalSectorManager().inspect().clientId;
 expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
 expect(second).not.toBe(first);
});
it.each([['1',1000],['9999',2000],['bad',100]])('honors bounded Retry-After %s',async(value,delay)=>{
 vi.useFakeTimers();const busy={...reply({},503),headers:{get:()=>value}};
 const fetcher=vi.fn().mockResolvedValueOnce(busy).mockResolvedValue(reply(manifest([])));
 const m=new PhysicalSectorManager({fetcher});const promise=m.load({milliseconds});
 await vi.advanceTimersByTimeAsync(delay-1);expect(fetcher).toHaveBeenCalledOnce();
 await vi.advanceTimersByTimeAsync(1);expect((await promise).objects).toEqual([]);
});
it('correlates each transport attempt and distinguishes a whole-selection revision retry',async()=>{
 let conflict=true;const events=[];
 const fetcher=vi.fn(async url=>{
  if(url.includes('nearby?'))return reply(manifest());
  if(conflict){conflict=false;return reply({},409);}
  return reply(frame(decodeURIComponent(url.split('sectors/')[1].split('?')[0])));
 });
 const m=new PhysicalSectorManager({fetcher,onRequest:event=>events.push(event)});
 await m.load({milliseconds});
 const headers=fetcher.mock.calls.map(call=>call[1].headers);
 expect(new Set(headers.map(h=>h['X-Astroverse-Request'])).size).toBe(headers.length);
 expect(new Set(headers.map(h=>h['X-Astroverse-Selection'])).size).toBe(2);
 expect(headers.every(h=>h['X-Astroverse-Client']===m.inspect().clientId)).toBe(true);
 expect(events).toHaveLength(headers.length);expect(events.some(e=>e.outcome==='conflict')).toBe(true);
});
it.each([502,503,504])('retries transient HTTP %i once with bounded backoff',async status=>{
 vi.useFakeTimers();const fetcher=vi.fn().mockResolvedValueOnce(reply({},status)).mockResolvedValue(reply(manifest([])));
 const m=new PhysicalSectorManager({fetcher});const pending=m.load({milliseconds});
 await vi.advanceTimersByTimeAsync(99);expect(fetcher).toHaveBeenCalledOnce();
 await vi.advanceTimersByTimeAsync(1);expect((await pending).objects).toEqual([]);expect(m.inspect().retries).toBe(1);
});
it('caps native network retries and releases cancelled backoff',async()=>{
 vi.useFakeTimers();const fetcher=vi.fn().mockRejectedValue(new TypeError('network'));
 const m=new PhysicalSectorManager({fetcher});const outcome=m.load({milliseconds}).catch(e=>e);
 await vi.advanceTimersByTimeAsync(101);expect((await outcome).message).toBe('network');expect(fetcher).toHaveBeenCalledTimes(2);
 const pending=m.load({milliseconds}).catch(e=>e);await vi.advanceTimersByTimeAsync(1);m.cancel();
 expect((await pending).name).toBe('AbortError');await vi.advanceTimersByTimeAsync(200);expect(fetcher).toHaveBeenCalledTimes(3);
});
it('aborts hung siblings and never starts queued sectors after partial failure',async()=>{
 let aborted=0;
 const fetcher=vi.fn(async(url,{signal})=>{
  if(url.includes('nearby?'))return reply(manifest(['a','b','c','d']));
  if(url.includes('/a?'))return reply({detail:{message:'permanent'}},422);
  return new Promise((_,reject)=>signal.addEventListener('abort',()=>{aborted++;reject(new DOMException('cancelled','AbortError'));}));
 });
 const m=new PhysicalSectorManager({fetcher,limits:{concurrency:2}});
 await expect(m.load({milliseconds})).rejects.toThrow('permanent');
 expect(fetcher).toHaveBeenCalledTimes(3);expect(aborted).toBe(1);expect(m.inspect()).toMatchObject({active:0,pending:0,queue:0,objects:0});
});
it('publishes reordered sectors atomically and accounts staging plus the previous set',async()=>{
 const finish=new Map();let delayed=false;
 const fetcher=vi.fn(async url=>{
  const body=url.includes('nearby?')?manifest():frame(decodeURIComponent(url.split('sectors/')[1].split('?')[0]));
  if(!delayed || url.includes('nearby?'))return reply(body);
  return new Promise(resolve=>finish.set(body.sector,()=>resolve(reply(body))));
 });
 const m=new PhysicalSectorManager({fetcher,limits:{concurrency:2}});await m.load({milliseconds,context:'continuous'});
 delayed=true;const pending=m.load({milliseconds,context:'continuous',retainPrevious:true});
 await vi.waitFor(()=>expect(finish.size).toBe(2));finish.get('b')();
 await vi.waitFor(()=>expect(finish.size).toBe(3));
 expect(m.inspect()).toMatchObject({residentObjects:3,pending:1,objects:4});expect(m.inspect().decoded).toBeGreaterThan(1000000);
 finish.get('c')();finish.get('a')();expect((await pending).objects.map(x=>x.id)).toEqual(['a','b','c']);
 expect(m.inspect()).toMatchObject({residentObjects:3,pending:0,objects:3,active:0});
});
it.each(['identity','unknown','bad-id','big-sector','registry'])('rejects invalid %s without retry',async kind=>{
 const f=frame('a');delete f.hierarchy;
 if(kind==='identity')f.objects=[{id:'a',position:[1,2,3],status:'computed',target:10},{id:'b',position:[1,2,3],status:'computed',target:10}];
 if(kind==='unknown')f.objects[0].status='unknown';
 if(kind==='bad-id')f.objects[0].id='';
 if(kind==='big-sector')f.objects=Array.from({length:129},(_,i)=>({id:String(i),position:null,status:'unknown'}));
 if(kind==='registry')f.registry_revision='';
 const fetcher=vi.fn(async()=>reply(f));const m=new PhysicalSectorManager({fetcher});
 await expect(m.load({milliseconds})).rejects.toThrow();expect(fetcher).toHaveBeenCalledOnce();
});
it('rejects old plus staging object exhaustion and recovers in a new context',async()=>{
 const m=new PhysicalSectorManager({fetcher:provider(),limits:{objects:4}});
 await m.load({milliseconds,context:'one'});
 await expect(m.load({milliseconds,context:'one',retainPrevious:true})).rejects.toThrow('objects');
 expect(m.inspect().objects).toBe(0);expect((await m.load({milliseconds,context:'two'})).objects).toHaveLength(3);
});
it('cannot mutate accounting when an obsolete body read finishes after timeout',async()=>{
 vi.useFakeTimers();let finish;
 const fetcher=vi.fn(async()=>({ok:true,status:200,json:()=>new Promise(resolve=>{finish=resolve;})}));
 const m=new PhysicalSectorManager({fetcher,limits:{timeout:20}});const result=m.load({milliseconds}).catch(e=>e);
 await vi.advanceTimersByTimeAsync(21);expect((await result).message).toContain('Timeout');finish(manifest());
 await vi.advanceTimersByTimeAsync(1);expect(m.inspect()).toMatchObject({active:0,pending:0,objects:0,serialized:0,decoded:0});
});
it('deduplicates an identical in-flight selection',async()=>{
 let finish;const fetcher=vi.fn(()=>new Promise(resolve=>{finish=resolve;}));
 const m=new PhysicalSectorManager({fetcher});const first=m.load({milliseconds});
 const second=m.load({milliseconds});const result=first.catch(e=>e);
 finish(reply(manifest([])));expect(await second).toHaveProperty('objects',[]);
 expect(await result).toHaveProperty('objects',[]);expect(fetcher).toHaveBeenCalledOnce();
});
it('drains cancel followed immediately by reload without exceeding transport concurrency',async()=>{
 const fetcher=vi.fn((url,{signal})=>new Promise((_,reject)=>{
   signal.addEventListener('abort',()=>reject(new DOMException('cancelled','AbortError')),{once:true});
 }));
 const m=new PhysicalSectorManager({fetcher,limits:{concurrency:1}});
 const old=m.load({milliseconds}).catch(e=>e);m.cancel();
 fetcher.mockResolvedValue(reply(manifest([])));
 const next=m.load({milliseconds});expect((await old).name).toBe('AbortError');
 expect((await next).objects).toEqual([]);expect(m.inspect().peakActive).toBe(1);
});
it('cancel releases resident accounting immediately',async()=>{
 const m=new PhysicalSectorManager({fetcher:provider()});await m.load({milliseconds});m.cancel();
 expect(m.inspect()).toMatchObject({objects:0,serialized:0,decoded:0,pending:0,queue:0});
});
function provider(change=x=>x) {return vi.fn(async url=>reply(change(url.includes('nearby?')?manifest():frame(decodeURIComponent(url.split('sectors/')[1].split('?')[0])),url)));}
it('atomically publishes reordered sectors, evicts and returns without accumulating sets',async()=>{
 const fetcher=provider();const m=new PhysicalSectorManager({fetcher,limits:{concurrency:2}});
 for(let i=0;i<10;i++) {const f=await m.load({milliseconds});expect(f.objects.map(x=>x.id)).toEqual(['a','b','c']);expect(f.hierarchy.sectors).toHaveLength(3);expect(m.inspect().objects).toBe(3);expect(m.inspect().pending).toBe(0);}
 expect(m.inspect().peakActive).toBe(2);expect(m.inspect().requests).toBe(40);
 m.cancel();expect(m.resident).toBe(null);
});
it.each([
 ['queue',1],['objects',1],['serialized',100],['decoded',100],['response',100]
])('rejects exhausted %s budget and releases staging',async(key,value)=>{
 const m=new PhysicalSectorManager({fetcher:provider(),limits:{[key]:value}});
 await expect(m.load({milliseconds})).rejects.toThrow();expect(m.resident).toBe(null);expect(m.inspect().pending).toBe(0);expect(m.inspect().objects).toBe(0);
});
it.each(['duplicate','mixed','tdb','registry','flat','identity','address'])('rejects incompatible %s without partial publication',async kind=>{
 const fetcher=provider((body,url)=>{
 if(url.includes('nearby?')) {if(kind==='duplicate')body.sectors.push(body.sectors[0]);return body;}
 if(kind==='mixed')body.coordinates={...body.coordinates,corrections:'LT'};
 if(kind==='tdb')body.jd_tdb++;
 if(kind==='registry')body.registry_revision='other';
 if(kind==='flat')delete body.hierarchy;
 if(kind==='identity'){body.objects[0].id='same';body.hierarchy.bodies[0].id='same';}
 if(kind==='address'){body.hierarchy.sectors[0].id='shared';body.hierarchy.sectors[0].origin_km=[body.sector==='a'?0:1,0,0];body.hierarchy.systems[0].sector_id='shared';body.hierarchy.systems[0].offset_km=[body.sector==='a'?0:-1,0,0];}
 return body;
 });
 // Mixed flat/hierarchy is invalid; all-flat remains a supported contract.
 if(kind==='flat')fetcher.mockImplementationOnce(async()=>reply(manifest())).mockImplementationOnce(async()=>reply(frame('a')));
 const m=new PhysicalSectorManager({fetcher});await expect(m.load({milliseconds})).rejects.toThrow();expect(m.resident).toBe(null);
});
it('bounds 409 recovery globally even when every sector conflicts',async()=>{
 const fetcher=vi.fn(async url=>url.includes('nearby?')?reply(manifest()):reply({},409));
 const m=new PhysicalSectorManager({fetcher});await expect(m.load({milliseconds})).rejects.toThrow('Ревизия');
 expect(fetcher).toHaveBeenCalledTimes(8);
});
it('retries whole selection on a conflict then publishes only the new revision',async()=>{
 let conflict=true;const fetcher=vi.fn(async url=>{if(url.includes('nearby?'))return reply(manifest());if(conflict){conflict=false;return reply({},409);}return reply(frame(decodeURIComponent(url.split('sectors/')[1].split('?')[0])));});
 const m=new PhysicalSectorManager({fetcher});expect((await m.load({milliseconds})).objects).toHaveLength(3);expect(fetcher).toHaveBeenCalledTimes(8);
});
it('times out a hung request, ignores late completion and permits recovery',async()=>{
 vi.useFakeTimers();let finish;
 const fetcher=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;}));
 const m=new PhysicalSectorManager({fetcher,limits:{timeout:20}});
 const outcome=m.load({milliseconds}).catch(e=>e);
 await vi.advanceTimersByTimeAsync(25);expect((await outcome).message).toContain('Timeout');
 finish(reply(manifest()));await vi.advanceTimersByTimeAsync(1);expect(m.inspect().objects).toBe(0);
 fetcher.mockImplementation(async()=>reply({...manifest([])}));expect((await m.load({milliseconds})).objects).toEqual([]);vi.useRealTimers();
});
it('cancels an obsolete generation even if fetch ignores abort',async()=>{
 let finish;const fetcher=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue(reply(manifest([])));
 const m=new PhysicalSectorManager({fetcher});const old=m.load({milliseconds}).catch(e=>e);
 expect((await m.load({milliseconds,context:'new area'})).objects).toEqual([]);finish(reply(manifest()));expect((await old).name).toBe('AbortError');expect(m.inspect().objects).toBe(0);
});
it('does not retry permanent HTTP errors or retain a previous success',async()=>{
 const fetcher=provider();const m=new PhysicalSectorManager({fetcher});await m.load({milliseconds});fetcher.mockResolvedValue(reply({detail:{message:'unsupported'}},422));
 await expect(m.load({milliseconds})).rejects.toThrow('unsupported');expect(fetcher).toHaveBeenCalledTimes(5);expect(m.resident).toBe(null);
});
it('rejects invalid limits and handles an already aborted signal',async()=>{
 expect(()=>new PhysicalSectorManager({limits:{queue:0}})).toThrow();const controller=new AbortController();controller.abort();
 await expect(new PhysicalSectorManager().load({milliseconds,signal:controller.signal})).rejects.toHaveProperty('name','AbortError');
});
it('reads bounded streaming HTTP bodies and rejects malformed/oversized streams',async()=>{
 const saved=globalThis.TextDecoder;
 const {TextDecoder}=await import('node:util');globalThis.TextDecoder=TextDecoder;
 for(const text of [JSON.stringify(manifest([])),'not JSON','x'.repeat(300000)]) {
 const bytes=new TextEncoder().encode(text);let done=false;
 const fetcher=vi.fn(async()=>({ok:true,status:200,body:{getReader:()=>({read:async()=>done?{done:true}:(done=true,{done:false,value:bytes}),cancel:vi.fn()})}}));
 const m=new PhysicalSectorManager({fetcher});if(text.startsWith('{'))expect((await m.load({milliseconds})).objects).toEqual([]);else await expect(m.load({milliseconds})).rejects.toThrow();
 }
 globalThis.TextDecoder=saved;
});
it('updates 2048 resident records and rejects a single-set-only budget before sector work',async()=>{
 const ids=Array.from({length:32},(_,i)=>String(i));
 const fetcher=vi.fn(async url=>{
  if(url.includes('nearby?'))return reply({...manifest(ids),sectors:ids.map(id=>({id,revision:'r',object_count:64}))});
  const id=decodeURIComponent(url.split('sectors/')[1].split('?')[0]),body=frame(id);delete body.hierarchy;
  body.objects=Array.from({length:64},(_,i)=>({id:id+':'+i,position:[Number(id)*1e6,i,0],status:'computed'}));return reply(body);
 });
 const m=new PhysicalSectorManager({fetcher});
 for(let i=0;i<5;i++){
  expect((await m.load({milliseconds,context:'Now',retainPrevious:true})).objects).toHaveLength(2048);
  expect(m.inspect()).toMatchObject({residentObjects:2048,active:0,pending:0});
 }
 expect(m.inspect().peakObjects).toBe(4096);expect(m.inspect().peakDecoded).toBeLessThanOrEqual(m.limits.decoded);
 const tight=new PhysicalSectorManager({fetcher,limits:{objects:2048}});
 await tight.load({milliseconds,context:'Now'});const before=fetcher.mock.calls.length;
 await expect(tight.load({milliseconds,context:'Now',retainPrevious:true})).rejects.toMatchObject({permanent:true});
 expect(fetcher.mock.calls.length-before).toBe(1);
 expect(tight.inspect().peakObjects).toBe(2048);expect(tight.inspect().objects).toBe(0);
});
it('rejects reservation before crossing a byte budget and marks it terminal',async()=>{
 const m=new PhysicalSectorManager({fetcher:provider(),limits:{decoded:100}});
 await expect(m.load({milliseconds,retainPrevious:true})).rejects.toMatchObject({permanent:true});
 expect(m.inspect()).toMatchObject({requests:0,peakDecoded:0,decoded:0});
});
