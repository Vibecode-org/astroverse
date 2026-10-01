import { useState, useEffect, useRef } from 'react';

const DAY_MS = 86400000;
const UPDATE_INTERVAL_MS = 100;
const MAX_FRAME_GAP_MS = 1000;

export function useTimeEngine() {
  const [simDate, setSimDate] = useState(() => new Date());
  // Скорость = симулированных СЕКУНД за реальную секунду. Раньше множитель
  // означал «дней за секунду», из-за чего ×1 был суточным ускорением, а
  // реального времени в приложении не существовало вовсе.
  const [timeMultiplier, setTimeMultiplier] = useState(1);
  const [isPaused, setIsPaused] = useState(false);
  const clockRef = useRef(null);

  useEffect(() => {
    let raf = null;
    let lastTime = performance.now();
    let elapsedSinceUpdate = 0;
    let pendingSimulationMs = 0;
    let paused = isPaused;
    let multiplier = timeMultiplier;
    let hidden = document.hidden;

    const flush = () => {
      // Capture the delta before resetting it: React may defer the updater.
      const delta = pendingSimulationMs;
      pendingSimulationMs = 0;
      elapsedSinceUpdate = 0;
      if (delta !== 0) {
        setSimDate(prev => new Date(prev.getTime() + delta));
      }
    };

    const advance = now => {
      const elapsed = now - lastTime;
      lastTime = now;
      // Ignore suspended frames, but retain the full elapsed time of normal frames.
      if (paused || hidden || elapsed < 0 || elapsed > MAX_FRAME_GAP_MS) return;
      // elapsed — миллисекунды реального времени, multiplier — сколько
      // симулированных секунд проходит за одну реальную, поэтому итог
      // сразу в миллисекундах без пересчёта на сутки.
      pendingSimulationMs += elapsed * multiplier;
      elapsedSinceUpdate += elapsed;
      if (elapsedSinceUpdate >= UPDATE_INTERVAL_MS) flush();
    };

    const tick = now => {
      raf = null;
      advance(now);
      schedule();
    };

    const schedule = () => {
      if (raf !== null) cancelAnimationFrame(raf);
      raf = !paused && !hidden ? requestAnimationFrame(tick) : null;
    };

    clockRef.current = (nextPaused, nextMultiplier) => {
      advance(performance.now());
      flush();
      paused = nextPaused;
      multiplier = nextMultiplier;
      schedule();
    };

    const onVisibilityChange = () => {
      advance(performance.now());
      flush();
      hidden = document.hidden;
      schedule();
    };

    document.addEventListener('visibilitychange', onVisibilityChange);
    schedule();

    return () => {
      if (raf !== null) cancelAnimationFrame(raf);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      clockRef.current = null;
    };
  }, []);

  useEffect(() => {
    clockRef.current?.(isPaused, timeMultiplier);
  }, [isPaused, timeMultiplier]);

  return { simDate, setSimDate, timeMultiplier, setTimeMultiplier, isPaused, setIsPaused };
}
