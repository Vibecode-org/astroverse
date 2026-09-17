import React from 'react';

const VIEWS = [
  { id: 'solar', label: 'Солнечная система', icon: '☼' },
  { id: 'local', label: 'Окрестности Солнца', icon: '✦' },
  { id: 'galaxy', label: 'Млечный Путь', icon: '◌' },
];

const ViewControls = ({ view, setView }) => {
  return (
    <div className="viewControls">
      {VIEWS.map((v) => (
        <button key={v.id} className={view === v.id ? 'viewBtn active' : 'viewBtn'}
          onClick={() => setView(v.id)}>
          <span>{v.icon}</span>{v.label}
        </button>
      ))}
    </div>
  );
};

export default ViewControls;