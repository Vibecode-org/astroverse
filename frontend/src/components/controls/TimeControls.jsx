import React from 'react';

const DAY_MS = 86400000;

export default function TimeControls ({ setSimDate, isPaused, setIsPaused, timeMultiplier, setTimeMultiplier }) {

  return (
    <div className="timeControls">
      <div className="timeControlBar">
        <div className="timeMain">
          <button type="button" className="timeBtn" onClick={() => setSimDate(new Date())}>
            <span>Сейчас</span>
          </button>
          <button type="button" className="timeBtn" onClick={() => setSimDate(prev => new Date(prev.getTime() + DAY_MS))}>
            <span>+1 день</span>
          </button>
          <button type="button" className="timeBtn" onClick={() => setSimDate(prev => new Date(prev.getTime() - DAY_MS))}>
            <span>-1 день</span>
          </button>
          <span className="sep">/</span>
          <button type="button" className="timeBtn" onClick={() => setTimeMultiplier(prev => prev * 1.5)}>
            <span>×1.5</span>
          </button>
          <button type="button" className="timeBtn" onClick={() => setTimeMultiplier(prev => prev / 2)}>
            <span>÷2</span>
          </button>
          <span className="speedChip" title="При ×1: один день симуляции за секунду">
            Скорость: ×{Number(timeMultiplier.toPrecision(4))}
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