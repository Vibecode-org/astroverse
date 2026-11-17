import { describe, it, expect, vi } from 'vitest';
import { SectorStore, SnapshotChanged } from '../src/data/sectorStore.js';
function response(data, status = 200, snapshot = 's1', etag = '"v1"') {
  return { ok: status >= 200 && status < 300, status, json: async () => data, text: async () => JSON.stringify(data),
    headers: new Headers({ 'X-Catalog-Snapshot': snapshot, etag }) };
}
const page = (ids, next_after = null) => ({ version: 'spatial/1', objects: ids.map(id => ({ object: { id }, coordinates: { status: 'unverified' } })), next_after });

describe('sector cards with bounded residency', () => {
  it('pins pages, revalidates 304 and never changes snapshot coordinate semantics', async () => {
    const fetcher=vi.fn().mockResolvedValueOnce(response({ snapshot:'s1',sector:{ id:'solar:system' } }))
      .mockResolvedValueOnce(response(page(['a'],'a'))).mockResolvedValueOnce(response(page(['b'])))
      .mockResolvedValueOnce(response(null,304)).mockResolvedValueOnce(response(null,304));
    const store=new SectorStore({fetcher});
    await store.locate('a'); const result=await store.load('solar:system');
    expect(result).toHaveLength(2); expect(result[0].coordinates.status).toBe('unverified');
    expect(fetcher.mock.calls[2][0]).toContain('snapshot=s1'); expect(fetcher.mock.calls[2][0]).toContain('after=a');
    const again=await store.load('solar:system'); expect(again).toEqual(result);
    expect(fetcher.mock.calls[3][1].headers).toEqual({'If-None-Match':'"v1"'});
    expect(store.entries.size).toBe(1);
  });
  it('evicts the oldest serialized sector with byte accounting', async () => {
    const bytes=JSON.stringify(page(['a'])).length*2+256;
    const store=new SectorStore({maxBytes:bytes+2,fetcher:vi.fn(async()=>response(page(['a'])))});
    await store.load('one'); await store.load('two');
    expect([...store.entries.keys()]).toEqual(['two']); expect(store.bytes).toBe(bytes);
    store.clear(); expect(store.bytes).toBe(0); expect(store.snapshot).toBe(null);
  });
  it('rejects oversized, malformed, or inconsistent pages', async () => {
    for (const [data,opts] of [[page(['a','b']),{maxObjects:1}], [page(['a']),{maxBytes:1}],
      [{...page(['a']),version:'v2'},{}],[page([], 'a'),{}], [page(['a'],'a'),{}]]) {
      const fetcher=vi.fn(async()=>response(data)); const store=new SectorStore({fetcher,...opts});
      await expect(store.load('sid')).rejects.toThrow(); expect(store.entries.size).toBe(0);
    }
    for (const reply of [response(null,500),response(null,304),response(page(['a']),200,'')]) {
      await expect(new SectorStore({fetcher:async()=>reply}).load('sid')).rejects.toThrow();
    }
    const store=new SectorStore({fetcher:async()=>response(page(['a']),200,'different')}); store.snapshot='old';
    await expect(store.load('sid')).rejects.toBeInstanceOf(SnapshotChanged);
    await expect(new SectorStore({fetcher:async()=>response(null,409)}).load('sid')).rejects.toBeInstanceOf(SnapshotChanged);
  });
  it('recovers once from publication changes while locating an unloaded object', async () => {
    const fetcher=vi.fn().mockResolvedValueOnce(response({snapshot:'s1',sector:{id:'old'}}))
      .mockResolvedValueOnce(response(null,409)).mockResolvedValueOnce(response({snapshot:'s2',sector:{id:'new'}},200,'s2'))
      .mockResolvedValueOnce(response(page(['target']),200,'s2'));
    const store=new SectorStore({fetcher}); const result=await store.object('target');
    expect(result.object.id).toBe('target'); expect(store.snapshot).toBe('s2');
    expect([...store.entries.keys()]).toEqual([]);
    const wrong=new SectorStore({fetcher:async()=>response({snapshot:'s2'})}); wrong.snapshot='s1';
    await expect(wrong.locate('a')).rejects.toBeInstanceOf(SnapshotChanged);
    await expect(new SectorStore({fetcher:async()=>response(null,404)}).locate('missing')).rejects.toThrow('404');
    await expect(new SectorStore({fetcher:async()=>response(null,409)}).object('a')).rejects.toBeInstanceOf(SnapshotChanged);
    const absent=new SectorStore({fetcher:vi.fn().mockResolvedValueOnce(response({snapshot:'s1',sector:{id:'x'}})).mockResolvedValueOnce(response(page([])))});
    await expect(absent.object('missing')).rejects.toThrow('отсутствует');
  });
});
