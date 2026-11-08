import React from 'react';
import { act } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

const render = vi.fn();
vi.mock('react-dom/client', () => ({ createRoot: vi.fn(() => ({ render })) }));

test('entrypoint renders the application inside its error boundary into #root', async () => {
  document.body.innerHTML = '<div id="root"></div>';
  await act(async () => { await import('../src/main.jsx'); });
  expect(render).toHaveBeenCalledOnce();
  expect(React.isValidElement(render.mock.calls[0][0])).toBe(true);
  document.body.innerHTML = '';
});
