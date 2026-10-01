export function kindLabel(kind) {
  return {
    star: 'звезда',
    planet: 'планета',
    dwarf_planet: 'карликовая планета',
    moon: 'спутник',
    exoplanet: 'экзопланета',
    nebula: 'туманность',
    cluster: 'звёздное скопление',
    black_hole: 'чёрная дыра',
    galaxy: 'галактика',
    asteroid: 'астероид',
    comet: 'комета',
  }[kind] || kind;
}

export function objectScale(obj) {
  if (obj.scale) return obj.scale;
  if (['planet', 'dwarf_planet', 'moon', 'asteroid', 'comet'].includes(obj.kind)) return 'solar';
  if (obj.kind === 'star' && obj.id === 'sun') return 'solar';
  if (['star', 'exoplanet'].includes(obj.kind)) return 'local';
  return 'galaxy';
}

// Расстояния, размеры и орбиты спутников считаются в solarLayout.js: там они
// считаются для всей системы сразу, поэтому соблюдаются зазоры между телами.
// Раньше эти функции жили здесь и считались независимо для каждого объекта,
// из-за чего орбита Луны оказывалась больше промежутка Земля—Венера.