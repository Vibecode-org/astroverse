import React, { useCallback, useEffect, useRef, useState } from 'react';
import { kindLabel } from '../../bodies/index.js';
import { safeColor } from '../../bodies/utils/colorUtils.js';

// Fixed row height keeps windowing simple and avoids layout thrash: only the
// rows inside the scroll viewport (plus a small overscan) are mounted. The
// catalog can hold 100k objects; mounting one <button> per object froze the
// tab for seconds and allocated tens of megabytes of DOM.
const ROW_HEIGHT = 34;
const OVERSCAN = 8;
const INITIAL_ROWS = 24;

const ObjectList = React.memo(function ObjectList({ displayObjects, loading, selected, setSelected }) {
  const listRef = useRef(null);
  const [range, setRange] = useState({ start: 0, end: INITIAL_ROWS });

  const updateRange = useCallback(() => {
    const el = listRef.current;
    if (!el) return;
    const height = el.clientHeight || 480;
    const start = Math.max(0, Math.floor(el.scrollTop / ROW_HEIGHT) - OVERSCAN);
    const end = Math.min(
      displayObjects.length,
      Math.ceil((el.scrollTop + height) / ROW_HEIGHT) + OVERSCAN,
    );
    setRange((prev) => (prev.start === start && prev.end === end ? prev : { start, end }));
  }, [displayObjects.length]);

  useEffect(() => {
    updateRange();
  }, [updateRange, displayObjects]);

  useEffect(() => {
    const el = listRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(updateRange);
    observer.observe(el);
    return () => observer.disconnect();
  }, [updateRange]);

  const start = Math.min(range.start, Math.max(displayObjects.length - 1, 0));
  const end = Math.min(range.end, displayObjects.length);
  const visible = displayObjects.slice(start, end);

  return (
    <div className="list" ref={listRef} onScroll={updateRange}>
      {loading && <div className="muted">Загрузка каталога…</div>}
      {!loading && (
        <div style={{ height: displayObjects.length * ROW_HEIGHT, position: 'relative' }}>
          {visible.map((o, i) => (
            <button
              key={o.id}
              className={selected?.id === o.id ? 'objectRow on' : 'objectRow'}
              style={{ position: 'absolute', top: (start + i) * ROW_HEIGHT, left: 0, right: 0 }}
              onClick={() => setSelected(o)}
            >
              {/* safeColor не пускает в CSSOM произвольную строку: color вида
                  url(https://…) иначе превратил бы поле в канал внешнего запроса. */}
              <span className="dot" style={{ background: safeColor(o.color) }} />
              <span className="objectName">{o.name}</span>
              <em>{kindLabel(o.kind)}</em>
            </button>
          ))}
        </div>
      )}
      {!loading && !displayObjects.length && <div className="muted">Ничего не найдено</div>}
    </div>
  );
});

export default ObjectList;
