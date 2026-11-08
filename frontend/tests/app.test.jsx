import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import App from '../src/components/layout/App.jsx';

vi.mock('../src/hooks/useThree.js', () => ({ useThree: () => ({ mountRef: { current: null } }) }));

const objects = [
  { id: 'earth', name: 'Земля', latin: 'Earth', kind: 'planet', scale: 'solar', description: 'home',
    facts: ['blue'], missions: ['Apollo'], source: 'NASA' },
  { id: 'sun', name: 'Sun', latin: 'Sun', kind: 'star', scale: 'solar', facts: [] },
  { id: 'host', name: 'Star', kind: 'star', scale: 'local' },
];
const json = data => ({ ok: true, json: async () => data });
function setup(search = () => json([])) {
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  for (const method of ['mark', 'measure'])
    Object.defineProperty(performance, method, { configurable: true, value: vi.fn() });
  vi.stubGlobal('fetch', vi.fn(async url => {
    if (url.startsWith('/api/search')) return search(url);
    if (url === '/api/objects?scale=solar') throw new Error('use JSON fallback');
    return json(objects);
  }));
  return render(<App />);
}

test('app selects objects, changes tabs, follows, closes and switches views', async () => {
  setup();
  await waitFor(() => expect(screen.getByText('Земля')).toBeTruthy());
  fireEvent.click(screen.getByText('Земля'));
  expect(screen.getByText('home')).toBeTruthy();
  fireEvent.click(screen.getByText('Телеметрия'));
  fireEvent.click(screen.getByText('Миссии')); expect(screen.getByText('Apollo')).toBeTruthy();
  fireEvent.click(screen.getByText('Факты')); expect(screen.getByText('blue')).toBeTruthy();
  fireEvent.click(screen.getByText('Обзор'));
  fireEvent.click(screen.getByText('Солнечная система'));
  fireEvent.click(screen.getByLabelText('Следить за объектом'));
  fireEvent.click(screen.getByText('×')); expect(screen.queryByText('home')).toBe(null);
  fireEvent.click(screen.getByText('Окрестности Солнца')); expect(screen.getByText('Star')).toBeTruthy();
});

test('debounced server search finds matches outside the binary metadata fields', async () => {
  const { unmount } = setup(() => json([{ id: 'earth' }]));
  await waitFor(() => expect(screen.getByText('Земля')).toBeTruthy());
  fireEvent.change(screen.getByLabelText('Поиск объектов'), { target: { value: 'NASA' } });
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('/api/search'))).toBe(true));
  await waitFor(() => expect(screen.queryByText('Sun')).toBe(null));
  expect(screen.getByText('Земля')).toBeTruthy();
  fireEvent.change(screen.getByLabelText('Поиск объектов'), { target: { value: '' } });
  await waitFor(() => expect(screen.getByText('Sun')).toBeTruthy());
  unmount();
});

test('search network failure retains client name filtering', async () => {
  setup(() => { throw new Error('offline'); });
  await waitFor(() => expect(screen.getByText('Земля')).toBeTruthy());
  fireEvent.change(screen.getByLabelText('Поиск объектов'), { target: { value: 'Earth' } });
  await waitFor(() => expect(screen.queryByText('Sun')).toBe(null));
  expect(screen.getByText('Земля')).toBeTruthy();
});

test('initial API failure displays an error without crashing the app', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
  vi.spyOn(console, 'warn').mockImplementation(() => {});
  vi.spyOn(console, 'error').mockImplementation(() => {});
  render(<App />);
  await waitFor(() => expect(screen.getByText('Ошибка API: offline')).toBeTruthy());
});
