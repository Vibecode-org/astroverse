import { useState, useEffect, useRef } from 'react';

export function useObjectData() {
  const [objects, setObjects] = useState([]);
  const [selected, setSelected] = useState(null);
  const [query, setQuery] = useState('');
  const [view, setView] = useState('solar');
  const [follow, setFollow] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errorDetails, setErrorDetails] = useState(null);
  const [panelTab, setPanelTab] = useState('overview');
  // По умолчанию реальный масштаб Солнечной системы: расстояния линейны по
  // а.е., размеры — настоящие радиусы Земли. Планеты при этом становятся
  // точками, и чтобы разглядеть систему, нужно подлететь к нужной.
  const [solarScale, setSolarScale] = useState('real');
  const appRef = useRef({});

  useEffect(() => {
    fetch('/api/objects')
      .then((r) => r.json())
      .then((data) => {
        setObjects(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error("API Fetch Error:", err);
        setErrorDetails("Ошибка API: " + err.message);
        setLoading(false);
      });
  }, []);

  return {
    objects, setObjects, selected, setSelected, query, setQuery,
    view, setView, follow, setFollow, loading, setLoading,
    errorDetails, setErrorDetails, panelTab, setPanelTab,
    appRef, solarScale, setSolarScale,
  };
}