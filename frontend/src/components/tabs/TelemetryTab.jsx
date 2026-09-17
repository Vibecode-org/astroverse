import React from 'react';

const TelemetryTab = ({ selected, formatNum, formatLy, formatPeriod }) => {
  return (
    <div className="tabContent">
      <div className="stats">
        {selected.gravity && <div><small>Гравитация</small><b>{selected.gravity}</b></div>}
        {selected.escape_velocity && <div><small>2-я космическая</small><b>{selected.escape_velocity}</b></div>}
        {selected.spectral_type && <div><small>Спектральный класс</small><b>{selected.spectral_type}</b></div>}
        {selected.temperature_k != null && <div><small>Температура</small><b>{formatNum(selected.temperature_k)} K</b></div>}
        {selected.au != null && <div><small>Большая полуось</small><b>{selected.au} а.е.</b></div>}
        {selected.period_days != null && <div><small>Период обращения</small><b>{formatPeriod(selected.period_days)}</b></div>}
        {selected.radius_km != null && <div><small>Радиус</small><b>{formatNum(selected.radius_km)} км</b></div>}
        {selected.radius_earth != null && <div><small>Радиус</small><b>{selected.radius_earth} R⊕</b></div>}
        {selected.mass_earth != null && <div><small>Масса</small><b>{selected.mass_earth} M⊕</b></div>}
        {selected.mass_sun != null && <div><small>Масса</small><b>{formatNum(selected.mass_sun)} M☉</b></div>}
        {selected.distance_ly != null && selected.distance_ly > 0 && <div><small>Расстояние от Солнца</small><b>{formatLy(selected.distance_ly)}</b></div>}
        {selected.apparent_magnitude != null && <div><small>Видимый блеск</small><b>{selected.apparent_magnitude} m</b></div>}
        {selected.schwarzschild_radius_km && <div><small>Радиус горизонта</small><b>{formatNum(selected.schwarzschild_radius_km)} км</b></div>}
      </div>
    </div>
  );
};

export default TelemetryTab;