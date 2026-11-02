import React from 'react';

const DAY_MS = 86400000;
const HOUR_S = 3600;
const DAY_S = 86400;
const WEEK_S = 604800;
const YEAR_S = 31557600;

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
  const sign = rate < 0 ? '−' : '';
  const value = Math.abs(rate);
  if (value < 60) return value < 10 ? `${sign}×${value}` : `${sign}×` + Math.round(value);
  if (value < HOUR_S) return `${sign}×${Math.round(value / 60)} мин/с`;
  if (value < DAY_S) return `${sign}×${Math.round(value / HOUR_S)} ч/с`;
  if (value < WEEK_S) return `${sign}×${Math.round(value / DAY_S)} д/с`;
  if (value < YEAR_S) return `${sign}×${Math.round(value / WEEK_S)} нед/с`;
  return `${sign}×` + Number((value / YEAR_S).toPrecision(3)) + ' год/с';
}

export default function TimeControls ({ setSimDate, isPaused, setIsPaused, timeMultiplier, setTimeMultiplier }) {
  const shift = (deltaMs) => setSimDate(prev => new Date(prev.getTime() + deltaMs));
  // Negative multipliers run the simulation backwards. Keep the magnitude for
  // rate matching and only flip the sign, so «−1 день/с» is a real direction.
  const magnitude = Math.abs(timeMultiplier) || 1;
  const reverse = timeMultiplier < 0;
  const nearest = RATES.reduce((best, r) =>
    Math.abs(Math.log(r.value / magnitude)) <
    Math.abs(Math.log(best.value / magnitude)) ? r : best, RATES[0]);

  const step = (dir) => {
    const i = RATES.indexOf(nearest);
    const next = RATES[Math.min(RATES.length - 1, Math.max(0, i + dir))];
    setTimeMultiplier(reverse ? -next.value : next.value);
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
            id="time-rate"
            name="timeRate"
            aria-label="Скорость симуляции"
            className="timeSelect"
            value={String(nearest.value)}
            onChange={(e) => setTimeMultiplier(reverse ? -Number(e.target.value) : Number(e.target.value))}
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
            className={`timeBtn${reverse ? ' active' : ''}`}
            aria-pressed={reverse}
            title="Обратный ход времени"
            onClick={() => setTimeMultiplier(-timeMultiplier)}
          >
            <span>⟲</span>
          </button>
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
