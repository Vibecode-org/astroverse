import React from 'react';
import { kindLabel } from '../../bodies/index.js';

const ObjectList = ({ displayObjects, loading, selected, setSelected }) => {
  return (
    <div className="list">
      {loading && <div className="muted">Загрузка каталога…</div>}
      {displayObjects.map((o) => (
        <button key={o.id} className={selected?.id === o.id ? 'objectRow on' : 'objectRow'} onClick={() => setSelected(o)}>
          <span className="dot" style={{ background: o.color || '#9fb4ff' }} />
          <span className="objectName">{o.name}</span>
          <em>{kindLabel(o.kind)}</em>
        </button>
      ))}
      {!loading && !displayObjects.length && <div className="muted">Ничего не найдено</div>}
    </div>
  );
};

export default ObjectList;