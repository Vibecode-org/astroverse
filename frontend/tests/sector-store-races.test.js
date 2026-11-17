import { expect, it, vi } from 'vitest';
import { SectorStore, SnapshotChanged } from '../src/data/sectorStore.js';
const page = {version:'spatial/1',objects:[{object:{id:'a'},coordinates:{status:'unverified'}}],next_after:null};
const reply = (snapshot='s1',status=200) => ({ok:status===200,status,headers:new Headers({'X-Catalog-Snapshot':snapshot,etag:'"tag"'}),text:async()=>JSON.stringify(page)});
const deferred = () => {let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
it('does not publish a cancelled sector even when transport ignores abort',async()=>{
 const body=deferred(),controller=new AbortController();
 const store=new SectorStore({fetcher:async()=>({...reply(),text:()=>body.promise})});
 const pending=store.load('old',controller.signal);await Promise.resolve();controller.abort();body.resolve(JSON.stringify(page));
 await expect(pending).rejects.toMatchObject({name:'AbortError'});
 expect(store.entries.size).toBe(0);expect(store.bytes).toBe(0);
});
it('does not let an old response clear or populate a replacement snapshot',async()=>{
 const old=deferred(),fetcher=vi.fn().mockReturnValueOnce(old.promise).mockResolvedValueOnce(reply('s2'));
 const store=new SectorStore({fetcher});const pending=store.load('old');
 store.clear();await store.load('new');old.resolve(reply('s1',409));
 await expect(pending).rejects.toBeInstanceOf(SnapshotChanged);
 expect(store.snapshot).toBe('s2');expect([...store.entries.keys()]).toEqual(['new']);
});
it('counts a concurrently revalidated sector once instead of exceeding its cache budget',async()=>{
 const first=deferred(),second=deferred(),fetcher=vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
 const store=new SectorStore({fetcher});const one=store.load('same'),two=store.load('same');
 first.resolve(reply());await one;second.resolve(reply());await two;
 expect(store.entries.size).toBe(1);expect(store.bytes).toBe(store.entries.get('same').bytes);
});
it('checks cancellation after decoding a locator before changing the snapshot',async()=>{
 const body=deferred(),controller=new AbortController();
 const store=new SectorStore({fetcher:async()=>({...reply(),json:()=>body.promise})});
 const pending=store.locate('a',controller.signal);await Promise.resolve();controller.abort();body.resolve({snapshot:'old',sector:{id:'old'}});
 await expect(pending).rejects.toMatchObject({name:'AbortError'});expect(store.snapshot).toBe(null);
});

it('rejects a decoded old body after replacement without repopulating the old sector',async()=>{
 const body=deferred(),fetcher=vi.fn().mockResolvedValueOnce({...reply(),text:()=>body.promise}).mockResolvedValueOnce(reply('s2'));
 const store=new SectorStore({fetcher});const pending=store.load('old');await Promise.resolve();
 store.clear();await store.load('new');body.resolve(JSON.stringify(page));
 await expect(pending).rejects.toBeInstanceOf(SnapshotChanged);
 expect(store.snapshot).toBe('s2');expect([...store.entries.keys()]).toEqual(['new']);
});
it('counts concurrent revalidations once when they both captured the same saved pages',async()=>{
 const first=deferred(),second=deferred(),fetcher=vi.fn().mockResolvedValueOnce(reply()).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
 const store=new SectorStore({fetcher});await store.load('same');
 const one=store.load('same'),two=store.load('same');first.resolve(reply());await one;second.resolve(reply());await two;
 expect(store.entries.size).toBe(1);expect(store.bytes).toBe(store.entries.get('same').bytes);
});

it('finds a card beyond 4096 family members while retaining only one bounded page',async()=>{
 let calls=0;const fetcher=vi.fn(async url=>{
   if(url.includes('/objects/'))return {...reply(),json:async()=>({snapshot:'s1',sector:{id:'large'}})};
   const after=new URL(url,'http://test').searchParams.get('after');const start=after===null?0:Number(after)+1;
   const ids=Array.from({length:512},(_,i)=>String(start+i).padStart(6,'0'));
   const data={...page,objects:ids.map(id=>({object:{id},coordinates:{status:'unverified'}})),next_after:ids.at(-1)};
   calls++;return {...reply(),text:async()=>JSON.stringify(data)};
 });
 const store=new SectorStore({fetcher});expect((await store.object('004500')).object.id).toBe('004500');
 expect(calls).toBe(9);expect(store.entries.size).toBe(0);expect(store.bytes).toBe(0);
 expect(fetcher.mock.calls.slice(1).every(([url])=>url.includes('snapshot=s1'))).toBe(true);
});
it('stops a family card scan on cancellation even if the next page resolves',async()=>{
 const pendingPage=deferred(),controller=new AbortController();
 const fetcher=vi.fn().mockResolvedValueOnce({...reply(),json:async()=>({snapshot:'s1',sector:{id:'large'}})})
   .mockResolvedValueOnce({...reply(),text:async()=>JSON.stringify({...page,next_after:'a'})}).mockReturnValueOnce(pendingPage.promise);
 const store=new SectorStore({fetcher}),pending=store.object('z',controller.signal);
 await vi.waitFor(()=>expect(fetcher).toHaveBeenCalledTimes(3));controller.abort();pendingPage.resolve(reply());
 await expect(pending).rejects.toMatchObject({name:'AbortError'});expect(store.entries.size).toBe(0);
});
it('restarts card scans from the locator after a mid-family publication change',async()=>{
 const fetcher=vi.fn().mockResolvedValueOnce({...reply(),json:async()=>({snapshot:'s1',sector:{id:'old'}})})
   .mockResolvedValueOnce({...reply(),text:async()=>JSON.stringify({...page,next_after:'a'})}).mockResolvedValueOnce(reply('s1',409))
   .mockResolvedValueOnce({...reply('s2'),json:async()=>({snapshot:'s2',sector:{id:'new'}})})
   .mockResolvedValueOnce({...reply('s2'),text:async()=>JSON.stringify({...page,objects:[{object:{id:'z'},coordinates:{status:'unverified'}}]})});
 const store=new SectorStore({fetcher});expect((await store.object('z')).object.id).toBe('z');
 expect(fetcher.mock.calls[4][0]).toContain('sectors/new?limit=512&snapshot=s2');expect(store.snapshot).toBe('s2');expect(store.entries.size).toBe(0);
});
it('uses the default fetch transport and rejects oversized or malformed card pages',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>({...reply(),json:async()=>({snapshot:'s1',sector:{id:'large'}})})));
 await new SectorStore().locate('a');expect(fetch).toHaveBeenCalled();vi.unstubAllGlobals();
 for(const [data,options,message] of [[page,{maxBytes:1},'лимит'],[{...page,version:'wrong'},{},'страница'],[{...page,objects:Array(513).fill(page.objects[0])},{},'страница'],[{...page,next_after:0},{},'продолжение'],[{...page,objects:[],next_after:'a'},{},'продолжение']]){
   const fetcher=vi.fn().mockResolvedValueOnce({...reply(),json:async()=>({snapshot:'s1',sector:{id:'large'}})}).mockResolvedValueOnce({...reply(),text:async()=>JSON.stringify(data)});
   await expect(new SectorStore({fetcher,...options}).object('z')).rejects.toThrow(message);
 }
});
