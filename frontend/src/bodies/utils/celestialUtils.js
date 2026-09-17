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

export function getSolarDistance(obj) {
  if (obj.id === 'sun') return 0;
  if (obj.au != null) {
    return 14.0 * Math.pow(obj.au, 0.72);
  }
  return obj.distance || 12;
}

export function getSolarSpeed(obj) {
  if (obj.au != null) {
    return 1.0 / Math.sqrt(obj.au);
  }
  return obj.speed || 0.1;
}

export function getMoonOrbitDistance(obj, parentRadius = 1.0) {
  if (obj.id === 'moon') return parentRadius * 3.4;
  if (obj.id === 'phobos') return parentRadius * 1.5;
  if (obj.id === 'deimos') return parentRadius * 2.3;
  if (obj.moon_distance) return parentRadius * (1.6 + obj.moon_distance * 0.45);
  return parentRadius * 2.8;
}