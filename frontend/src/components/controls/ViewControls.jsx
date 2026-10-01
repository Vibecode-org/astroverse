import React from 'react';

const VIEWS = [
  { id: 'solar', label: 'Солнечная система', icon: '☼' },
  { id: 'local', label: 'Окрестности Солнца', icon: '✦' },
  { id: 'galaxy', label: 'Млечный Путь', icon: '◌' },
];

const ViewControls = ({ view, setView, solarScale, setSolarScale }) => {
  return (
    <div className="viewControls">
      {VIEWS.map((v) => (
        <button key={v.id} className={view === v.id ? 'viewBtn active' : 'viewBtn'}
          onClick={() => setView(v.id)}>
          <span>{v.icon}</span>{v.label}
        </button>
      ))}
      <button
        className={solarScale === 'real' ? 'viewBtn active' : 'viewBtn'}
        onClick={() => setSolarScale(solarScale === 'real' ? 'compact' : 'real')}
        title="Реальный масштаб: расстояния линейны по а.е., размеры — в радиусах Земли. Планеты становятся точками, зато пропорции настоящие."
      >
        <span>⚖</span>{solarScale === 'real' ? 'Реальный масштаб' : 'Компактный'}
      </button>
    </div>
  );
};

export default ViewControls;