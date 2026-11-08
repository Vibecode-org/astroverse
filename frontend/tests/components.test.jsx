import React, { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';
import TimeControls from '../src/components/controls/TimeControls.jsx';
import ViewControls from '../src/components/controls/ViewControls.jsx';
import SearchBar from '../src/components/ui/SearchBar.jsx';
import ObjectList from '../src/components/ui/ObjectList.jsx';
import OverviewTab from '../src/components/tabs/OverviewTab.jsx';
import TelemetryTab from '../src/components/tabs/TelemetryTab.jsx';
import MissionsTab from '../src/components/tabs/MissionsTab.jsx';
import FactsTab from '../src/components/tabs/FactsTab.jsx';
import ErrorBoundary from '../src/components/ErrorBoundary.jsx';
import * as format from '../src/utils/formatUtils.js';

test('time controls shift dates, pause, select rates, clamp steps and reverse direction', () => {
  function Harness() {
    const [date, setSimDate] = useState(new Date(0));
    const [isPaused, setIsPaused] = useState(false);
    const [timeMultiplier, setTimeMultiplier] = useState(60);
    return <><output>{date.getTime()}</output><TimeControls {...{ setSimDate, isPaused, setIsPaused,
      timeMultiplier, setTimeMultiplier }} /></>;
  }
  render(<Harness />);
  fireEvent.click(screen.getByText('+1 день')); expect(screen.getByRole('status').textContent).toBe('86400000');
  fireEvent.click(screen.getByText('−1 день')); expect(screen.getByRole('status').textContent).toBe('0');
  fireEvent.click(screen.getByText('Пауза')); expect(screen.getByText('Продолжить')).toBeTruthy();
  fireEvent.click(screen.getByText('Продолжить')); expect(screen.getByText('Пауза')).toBeTruthy();
  fireEvent.click(screen.getByTitle('Обратный ход времени'));
  for (const value of ['3600', '86400', '604800', '31557600', '1', '60']) {
    fireEvent.change(screen.getByLabelText('Скорость симуляции'), { target: { value } });
    expect(document.querySelector('.speedChip').textContent).toContain('−');
  }
  fireEvent.click(screen.getByLabelText('Ускорить'));
  fireEvent.click(screen.getByLabelText('Замедлить'));
  fireEvent.click(screen.getByText('Сейчас')); expect(Number(screen.getByRole('status').textContent)).toBeGreaterThan(0);
});

test.each([0, 20, 120, 7200, 172800, 1209600, 63115200])('rate label handles custom magnitude %s', rate => {
  render(<TimeControls setSimDate={vi.fn()} setIsPaused={vi.fn()} timeMultiplier={rate} setTimeMultiplier={vi.fn()} />);
  expect(document.querySelector('.speedChip').textContent).toMatch(/×/);
});

test('view switches, scale toggles and search input call their handlers', () => {
  const setView = vi.fn(), setSolarScale = vi.fn(), setQuery = vi.fn();
  const { rerender } = render(<ViewControls view="solar" setView={setView} solarScale="compact" setSolarScale={setSolarScale} />);
  fireEvent.click(screen.getByText('Млечный Путь')); expect(setView).toHaveBeenCalledWith('galaxy');
  fireEvent.click(screen.getByText('Компактный')); expect(setSolarScale).toHaveBeenCalledWith('real');
  rerender(<ViewControls view="galaxy" setView={setView} solarScale="real" setSolarScale={setSolarScale} />);
  fireEvent.click(screen.getByText('Реальный масштаб')); expect(setSolarScale).toHaveBeenLastCalledWith('compact');
  render(<SearchBar query="" setQuery={setQuery} />);
  fireEvent.change(screen.getByLabelText('Поиск объектов'), { target: { value: 'Земля' } });
  expect(setQuery).toHaveBeenCalledWith('Земля');
});

test('object list windows 100k rows, scrolls, selects and handles an empty result after scrolling', () => {
  const objects = Array.from({ length: 100000 }, (_, i) => ({ id: String(i), name: `Star ${i}`, kind: 'star', color: '#fff' }));
  const selected = vi.fn(), disconnect = vi.fn(), observe = vi.fn();
  vi.stubGlobal('ResizeObserver', class { constructor(callback) { this.callback = callback; } observe = observe; disconnect = disconnect; });
  const { container, rerender, unmount } = render(<ObjectList displayObjects={objects} selected={objects[0]} setSelected={selected} loading={false} />);
  expect(container.querySelectorAll('button').length).toBeLessThan(40);
  fireEvent.click(screen.getByText('Star 0')); expect(selected).toHaveBeenCalledWith(objects[0]);
  const list = container.querySelector('.list'); list.scrollTop = 34000; fireEvent.scroll(list);
  expect(screen.queryByText('Star 0')).toBe(null); expect(screen.getByText('Star 1000')).toBeTruthy();
  rerender(<ObjectList displayObjects={[]} selected={null} setSelected={selected} loading={false} />);
  expect(screen.getByText('Ничего не найдено')).toBeTruthy();
  rerender(<ObjectList displayObjects={[]} setSelected={selected} loading={true} />);
  expect(screen.getByText('Загрузка каталога…')).toBeTruthy();
  unmount(); expect(observe).toHaveBeenCalled(); expect(disconnect).toHaveBeenCalled();
});

test('object tabs tolerate missing metadata and render all supported fields', () => {
  const { rerender } = render(<OverviewTab selected={{}} />);
  rerender(<OverviewTab selected={{ description: 'description', structure: 'layers', composition: 'iron' }} />);
  expect(screen.getByText('iron')).toBeTruthy();
  rerender(<FactsTab />); rerender(<FactsTab facts={['fact']} />); expect(screen.getByText('fact')).toBeTruthy();
  rerender(<MissionsTab missions="bad" />);
  rerender(<MissionsTab missions={['Mission', { name: 'Name', desc: 'Details' }, null]} />);
  expect(screen.getByText('Details')).toBeTruthy();
  rerender(<TelemetryTab selected={{}} {...format} />);
  rerender(<TelemetryTab selected={{ gravity: '1g', escape_velocity: '11km/s', spectral_type: 'G',
    temperature_k: 0, au: 1, period_days: 365, radius_km: 1, radius_earth: 1, mass_earth: 1,
    mass_sun: 1, distance_ly: 1, apparent_magnitude: 0, schwarzschild_radius_km: 2 }} {...format} />);
  expect(screen.getByText('0 K')).toBeTruthy(); expect(screen.getByText('0 m')).toBeTruthy();
});

test('render error boundary preserves normal content and explains escaped render errors', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const { rerender } = render(<ErrorBoundary><p>normal</p></ErrorBoundary>);
  expect(screen.getByText('normal')).toBeTruthy();
  function Broken() { throw new Error('test render failure'); }
  const expectedError = event => { if (event.error?.message === 'test render failure') event.preventDefault(); };
  window.addEventListener('error', expectedError);
  try { rerender(<ErrorBoundary><Broken /></ErrorBoundary>); }
  finally { window.removeEventListener('error', expectedError); }
  expect(screen.getByText('Приложение упало при отрисовке')).toBeTruthy();
  expect(screen.getByText(/test render failure/)).toBeTruthy();
});
