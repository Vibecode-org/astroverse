import { act, renderHook, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { useObjectData } from '../src/hooks/useObjectData.js';
import { useTimeEngine } from '../src/hooks/useTimeEngine.js';

const fixture = JSON.parse(readFileSync('../tests/fixtures/binary_catalog.json', 'utf8'));
const buffer = () => Uint8Array.from(Buffer.from(fixture.v2, 'base64')).buffer;
const json = data => ({ ok: true, json: async () => data });
const binary = () => ({ ok: true, arrayBuffer: async () => buffer() });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

function dataSetup(fetch) {
  vi.stubGlobal('fetch', fetch);
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  for (const method of ['mark', 'measure'])
    Object.defineProperty(performance, method, { configurable: true, value: vi.fn() });
  Object.defineProperty(performance, 'getEntriesByName', {
    configurable: true, value: () => [{ duration: 1 }],
  });
}

test('hybrid loader merges solar JSON with binary and lazily loads selected details', async () => {
  const solar = [{ id: 'sun', name: 'Sun', scale: 'solar', kind: 'star', description: 'solar' }];
  const fetch = vi.fn().mockResolvedValueOnce(json(solar)).mockResolvedValueOnce(binary())
    .mockResolvedValueOnce(json({ id: 'host', description: 'details', facts: ['fact'] }));
  dataSetup(fetch);
  const { result } = renderHook(useObjectData);
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.objects.map(o => o.id)).toEqual(['sun', 'host', 'planet', 'hole']);
  expect(result.current.catalogInfo.source).toBe('binary-v2');
  act(() => result.current.setSelected(result.current.objects[1]));
  await waitFor(() => expect(result.current.selected.description).toBe('details'));
  expect(result.current.selected._detailsLoaded).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(3);
});

test.each(['solar-http', 'binary-http', 'binary-parse', 'network'])(
  'loader recovers via full JSON after %s failure', async failure => {
    const fetch = vi.fn();
    if (failure === 'network') fetch.mockRejectedValueOnce(new Error('offline'));
    else if (failure === 'solar-http') fetch.mockResolvedValueOnce({ ok: false, status: 503 });
    else {
      fetch.mockResolvedValueOnce(json([]));
      fetch.mockResolvedValueOnce(failure === 'binary-http' ? { ok: false, status: 500 } :
        { ok: true, arrayBuffer: async () => new ArrayBuffer(0) });
    }
    fetch.mockResolvedValueOnce(json(fixture.objects)); dataSetup(fetch);
    const { result } = renderHook(useObjectData);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.catalogInfo.source).toBe('json-fallback');
    expect(result.current.objects).toEqual(fixture.objects);
    expect(result.current.errorDetails).toBe(null);
  });

test('all load paths failing shows a recoverable error and stops the loading indicator', async () => {
  dataSetup(vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ ok: false, status: 502 }));
  const { result } = renderHook(useObjectData);
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(result.current.errorDetails).toContain('502');
});

test('late details for a previous selection cannot overwrite the current selection', async () => {
  const details = deferred();
  const fetch = vi.fn().mockResolvedValueOnce(json([])).mockResolvedValueOnce(binary())
    .mockReturnValueOnce(details.promise).mockResolvedValueOnce(json({ id: 'planet', description: 'planet' }));
  dataSetup(fetch);
  const { result, unmount } = renderHook(useObjectData);
  await waitFor(() => expect(result.current.loading).toBe(false));
  act(() => result.current.setSelected(result.current.objects[0]));
  act(() => result.current.setSelected(result.current.objects[1]));
  await waitFor(() => expect(result.current.selected.description).toBe('planet'));
  await act(async () => details.resolve(json({ id: 'host', description: 'stale' })));
  expect(result.current.selected.id).toBe('planet');
  unmount();
});

test.each(['http', 'network'])('detail %s failure leaves the compact selection usable', async failure => {
  const fetch = vi.fn().mockResolvedValueOnce(json([])).mockResolvedValueOnce(binary());
  if (failure === 'http') fetch.mockResolvedValueOnce({ ok: false });
  else fetch.mockRejectedValueOnce(new Error('offline'));
  dataSetup(fetch);
  const { result } = renderHook(useObjectData);
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => result.current.setSelected(result.current.objects[0]));
  expect(result.current.selected.id).toBe('host');
  expect(result.current.selected._detailsLoaded).toBeUndefined();
});

function clockSetup() {
  let now = 0, id = 0, hidden = false;
  const frames = new Map();
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  vi.spyOn(document, 'hidden', 'get').mockImplementation(() => hidden);
  vi.stubGlobal('requestAnimationFrame', vi.fn(callback => { frames.set(++id, callback); return id; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn(key => frames.delete(key)));
  const hook = renderHook(useTimeEngine);
  const initial = hook.result.current.simDate.getTime();
  const step = ms => act(() => {
    now += ms;
    const pending = [...frames.values()]; frames.clear();
    pending.forEach(cb => cb(now));
  });
  const visibility = value => act(() => {
    hidden = value; document.dispatchEvent(new Event('visibilitychange'));
  });
  return { ...hook, initial, step, visibility, frames };
}

test('clock batches at 10Hz and uses seconds-per-second multipliers in both directions', () => {
  const { result, initial, step } = clockSetup();
  step(40); expect(result.current.simDate.getTime()).toBe(initial);
  step(60); expect(result.current.simDate.getTime()).toBe(initial + 100);
  act(() => result.current.setTimeMultiplier(60));
  step(100); expect(result.current.simDate.getTime()).toBe(initial + 6100);
  act(() => result.current.setTimeMultiplier(-60));
  step(100); expect(result.current.simDate.getTime()).toBe(initial + 100);
});

test('pause flushes partial intervals, stops scheduling and resumes without a time jump', () => {
  const { result, initial, step, frames } = clockSetup();
  step(40);
  act(() => result.current.setIsPaused(true));
  expect(result.current.simDate.getTime()).toBe(initial + 40);
  expect(frames.size).toBe(0);
  step(5000);
  act(() => result.current.setIsPaused(false));
  step(100); expect(result.current.simDate.getTime()).toBe(initial + 140);
});

test('tab suspension, negative frame deltas and teardown cannot advance or leak the clock', () => {
  const { result, initial, step, visibility, unmount, frames } = clockSetup();
  step(5000); step(-100); expect(result.current.simDate.getTime()).toBe(initial);
  visibility(true); expect(frames.size).toBe(0);
  step(10000); visibility(false); step(100);
  expect(result.current.simDate.getTime()).toBe(initial + 100);
  unmount(); expect(frames.size).toBe(0);
  visibility(true); expect(frames.size).toBe(0);
});
