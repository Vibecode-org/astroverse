import React from 'react';

const DAY_MS = 86400000;
const HOUR_MS = 3600000;

// Скорость = симулированных секунд за реальную секунду. Подписи human-readable,
// чтобы не считать нули в множителе: ×86400 читается хуже, чем «1 день/с».
const RATES = [
  { value: 1, label: 'Реальная', hint: '1 с за 1 с' },
  { value: 60, label: '1 мин/с' },
  { value: 3600, label: '1 час/с' },
  { value: 86400, label: '1 день/с' },
  { value: 604800, label: '1 нед/с' },
  { value: 31557600, label: '1 год/с' },
];

function formatRate(rate) {
  if (rate < 60) return rate < 10 ? `×${rate}` : '×' + Math.round(rate);
  if (rate < 3600) return `×${Math.round(rate / 60)} мин/с`;
  if (rate < 86400) return `×${Math.round(rate / HOUR_MS)} ч/с`;
  if (rate < 604800) return `×${Math.round(rate / DAY_MS)} д/с`;
  return '×' + (rate / 31557600).toPrecision(3) + ' год/с';
}

export default function TimeControls ({ setSimDate, isPaused, setIsPaused, timeMultiplier, setTimeMultiplier }) {
  const shift = (deltaMs) => setSimDate(prev => new Date(prev.getTime() + deltaMs));
  const nearest = RATES.reduce((best, r) =>
    Math.abs(Math.log(r.value)) - Math.log(timeMultiplier) <
    Math.abs(Math.log(best.value)) - Math.log(timeMultiplier) ? r : best, RATES[0]);

  const step = (dir) => {
    const i = RATES.indexOf(nearest);
    const next = RATES[Math.min(RATES.length - 1, Math.max(0, i + dir))];
    setTimeMultiplier(next.value);
  };

  return (
    <div className="timeControls">
      <div className="timeControlBar">
        <div className="timeMain">
          <button type="button" className="timeBtn" onClick={() => setSimDate(new Date())}>
            <span>Сейчас</span>
          </button>
          <button type="button" className="timeBtn" onClick={() => shift(-DAY_MS)}>
            <span>−1 день</span>
          </button>
          <button type="button" className="timeBtn" onClick={() => shift(DAY_MS)}>
            <span>+1 день</span>
          </button>
          <span className="sep">/</span>
          <button type="button" className="timeBtn" onClick={() => step(-1)}
            disabled={nearest === RATES[0]} aria-label="Замедлить">
            <span>◀◀</span>
          </button>

          <select
            className="timeSelect"
            value={String(nearest.value)}
            onChange={(e) => setTimeMultiplier(Number(e.target.value))}
            title="Скорость симуляции"
          >
            {RATES.map(r => <option key={r.value} value={String(r.value)}>{r.label}</option>)}
          </select>

          <button type="button" className="timeBtn" onClick={() => step(1)}
            disabled={nearest === RATES[RATES.length - 1]} aria-label="Ускорить">
            <span>▶▶</span>
          </button>
          <span className="speedChip" title={nearest.hint || 'Симулированных секунд за реальную секунду'}>
            {formatRate(timeMultiplier)}
          </span>
          <button
            type="button"
            className={`timeBtn${isPaused ? ' active' : ''}`}
            aria-pressed={isPaused}
            onClick={() => setIsPaused(prev => !prev)}
          >
            <span>{isPaused ? 'Продолжить' : 'Пауза'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
