import React from 'react';
import { kindLabel } from '../../bodies/index.js';
import { safeColor } from '../../bodies/utils/colorUtils.js';

const ObjectList = ({ displayObjects, loading, selected, setSelected }) => {
  return (
    <div className="list">
      {loading && <div className="muted">Загрузка каталога…</div>}
      {displayObjects.map((o) => (
        <button key={o.id} className={selected?.id === o.id ? 'objectRow on' : 'objectRow'} onClick={() => setSelected(o)}>
          {/* safeColor не пускает в CSSOM произвольную строку: color вида
              url(https://…) иначе превратил бы поле в канал внешнего запроса. */}
          <span className="dot" style={{ background: safeColor(o.color) }} />
          <span className="objectName">{o.name}</span>
          <em>{kindLabel(o.kind)}</em>
        </button>
      ))}
      {!loading && !displayObjects.length && <div className="muted">Ничего не найдено</div>}
    </div>
  );
};

export default ObjectList;