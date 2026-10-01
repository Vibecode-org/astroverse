/** Раскладка Солнечной системы.
 *
 * Раньше каждое тело считалось независимо: `getSolarDistance` давал
 * `14 · au^0.72`, а `getMoonOrbitDistance` — жёсткие коэффициенты, из-за чего
 * орбита Луны (3.4) оказывалась БОЛЬШЕ промежутка между Землёй и Венерой
 * (2.92) — Луна проходила сквозь Венеру. Кроме того, все луны одной планеты
 * получали одинаковую орбиту, потому что поле `moon_distance` не читалось.
 *
 * Здесь раскладка считается один раз для всей системы, поэтому соблюдаются
 * три гарантии:
 *   1. расстояния монотонны по большой полуоси, никто не наезжает на соседа;
 *   2. орбита спутника всегда внутри кольца «поверхность планеты → половина
 *      зазора до ближайшего соседа»;
 *   3. луны одной планеты идут по разным окружностям И в разных плоскостях,
 *      поэтому не пересекаются даже при близких радиусах.
 *
 * Масштабы: размеры — реальные, в радиусах Земли. Солнце — единственное
 * исключение (настоящие 109 R⊕ поглотили бы Меркурий при любом сжатии
 * расстояний, которое ещё держит систему в одном кадре); это тот же
 * осознанный компромисс, что и в SpaceEngine.
 */

import { hashUnit } from './utils/hash.js';

const EARTH_RADIUS_KM = 6371;
const AU_IN_KM = 149597870.7;
const AU_IN_EARTH_RADII = AU_IN_KM / EARTH_RADIUS_KM;   // 23 481
const SUN_RADIUS_KM = 696340;

// Два режима масштаба. `compact` держит систему в одном кадре, `real` даёт
// настоящие пропорции: тогда Юпитер — это 11 R⊕ на расстоянии 122 000 R⊕,
// и планеты действительно точки. Пользователь просил реальные пропорции,
// поэтому `real` — режим по умолчанию.
const SCALE_MODES = { REAL: 'real', COMPACT: 'compact' };
let activeScale = SCALE_MODES.REAL;

export function setSolarScale(mode) {
  activeScale = mode === SCALE_MODES.COMPACT ? SCALE_MODES.COMPACT : SCALE_MODES.REAL;
}

export function getSolarScale() {
  return activeScale;
}

export function solarScaleModes() {
  return SCALE_MODES;
}

const COMPACT_DISTANCE_BASE = 30;
const COMPACT_DISTANCE_EXPONENT = 0.58;
const COMPACT_SUN_RADIUS = 7;

// Мелкие тела: их реальный радиус (Церера — 0.00026 R⊕) неразличим, поэтому
// для них остаётся авторское значение, но с нижней границей видимости.
const SMALL_KINDS = new Set(['asteroid', 'comet']);
const SMALL_BODY_MIN_RADIUS = 0.4;
const SMALL_BODY_MIN_RADIUS_COMPACT = 0.4;

const TAU = Math.PI * 2;

/** Отображаемый радиус тела.
 *
 * Для планет и звёзд берётся физический `radius_km`, поэтому пропорции
 * настоящие. Для астероидов и комет физический радиус бесполезен (видимый
 * размер задаёт правдоподобность картинки), оставляем авторский `radius`.
 */
export function getBodyRadius(obj) {
  const compact = activeScale === SCALE_MODES.COMPACT;
  if (obj.id === 'sun') {
    return compact ? COMPACT_SUN_RADIUS : SUN_RADIUS_KM / EARTH_RADIUS_KM;
  }
  if (SMALL_KINDS.has(obj.kind)) {
    return Math.max(obj.radius || 0.4, SMALL_BODY_MIN_RADIUS_COMPACT);
  }
  if (obj.radius_km > 0) return obj.radius_km / EARTH_RADIUS_KM;
  return obj.radius || 0.4;
}

/** Расстояние от Солнца. В режиме `real` — линейно по а.е., как в реальности. */
export function getSolarDistance(obj) {
  if (obj.id === 'sun') return 0;
  const au = obj.au;
  if (typeof au === 'number' && Number.isFinite(au) && au > 0) {
    return activeScale === SCALE_MODES.REAL
      ? au * AU_IN_EARTH_RADII
      : COMPACT_DISTANCE_BASE * Math.pow(au, COMPACT_DISTANCE_EXPONENT);
  }
  return obj.distance || (activeScale === SCALE_MODES.REAL ? AU_IN_EARTH_RADII : COMPACT_DISTANCE_BASE);
}

/**
 * Считает расстояния и орбиты спутников для всей системы.
 *
 * @param {Array} objects каталог
 * @returns {Map<string, {distance:number, radius:number, moonOrbit:number,
 *   moonInclination:number, moonPhase:number}>} по id
 */
export function buildSolarLayout(objects) {
  const layout = new Map();
  // Соседи для расчёта места нужны ТОЛЬКО среди планет и карликовых.
  // Астероиды и кометы при этом лежат где угодно: если включить их, то
  // ближайшим «соседом» Юпитера окажется астероид с почти такой же полуосью,
  // и все его луны сядут на одну орбиту.
  const bodies = objects.filter(
    (o) => o.scale === 'solar' && (o.kind === 'planet' || o.kind === 'dwarf_planet')
      && o.parent === 'sun' && getSolarDistance(o) > 0,
  );

  for (const obj of objects) {
    if (obj.scale !== 'solar') continue;
    layout.set(obj.id, {
      distance: getSolarDistance(obj),
      radius: getBodyRadius(obj),
      moonOrbit: 0,
      moonInclination: 0,
      moonPhase: 0,
    });
  }

  const ordered = bodies.slice().sort((a, b) => layout.get(a.id).distance - layout.get(b.id).distance);

  // Сколько места остаётся до ПОВЕРХНОСТИ ближайшего соседа. Именно это
  // ограничивает орбиты спутников: считать до центра соседа нельзя —
  // Церера (карликовая между Марсом и Юпитером) тогда «съедает» место
  // лунам Юпитера, хотя сама меньше Меркурия.
  for (let i = 0; i < ordered.length; i++) {
    const entry = layout.get(ordered[i].id);
    const prev = i > 0 ? layout.get(ordered[i - 1].id) : null;
    const next = i < ordered.length - 1 ? layout.get(ordered[i + 1].id) : null;
    entry.room = Math.min(
      prev ? entry.distance - prev.distance - prev.radius : Infinity,
      next ? next.distance - entry.distance - next.radius : Infinity,
    );
  }

  // Спутники: концентрические окружности по реальному moon_distance и разные
  // плоскости, чтобы они не накладывались друг на друга.
  const moonsByParent = new Map();
  for (const obj of objects) {
    if (obj.scale !== 'solar' || obj.kind !== 'moon') continue;
    if (!moonsByParent.has(obj.parent)) moonsByParent.set(obj.parent, []);
    moonsByParent.get(obj.parent).push(obj);
  }

  for (const [parentId, moons] of moonsByParent) {
    const parent = layout.get(parentId);
    if (!parent) continue;
    const sorted = moons.slice().sort(
      (a, b) => (a.moon_distance || 0) - (b.moon_distance || 0),
    );
    const moonRadius = Math.max(...sorted.map((m) => getBodyRadius(m)));
    const inner = parent.radius * 1.15 + moonRadius;
    // Никогда не выходим за 42% места до поверхности соседа — это и есть
    // защита от «Луна проходит сквозь Венеру».
    const room = parent.room ?? Infinity;
    const outer = room === Infinity ? inner * 2.5 : inner + room * 0.42;
    const span = Math.max(0.05, outer - inner);

    // В реальном масштабе берём настоящую большую полуось из moon_distance_km:
    // поле moon_distance в снимке сжатое (у Луны 2.5 вместо 384 400 км) и для
    // настоящих пропорций не годится. Верхняя граница всё равно действует как
    // страховка на случай нереальных данных.
    const real = activeScale === SCALE_MODES.REAL;

    sorted.forEach((moon, index) => {
      const entry = layout.get(moon.id);
      if (!entry) return;
      const measured = real && moon.moon_distance_km > 0
        ? moon.moon_distance_km / EARTH_RADIUS_KM
        : null;
      if (measured !== null) {
        entry.moonOrbit = Math.min(Math.max(measured, inner), outer);
      } else {
        const t = (index + 0.5) / sorted.length;
        entry.moonOrbit = inner + span * t;
      }
      entry.moonInclination = hashUnit(moon.id + ':inc') * 0.9 - 0.45;
      entry.moonPhase = hashUnit(moon.id + ':phase') * TAU;
    });
  }

  return layout;
}

/** Границы декоративных поясов.
 *
 * Раньше радиусы были захардкожены (24.5–33 и 168–238) и не пережили смену
 * шкалы расстояний: реальные астероиды оказались на 45–58, и в сцене
 * появились две расходящиеся полосы, которые и читались как «ряд из комет».
 *
 * Границы задаются в а.е. и пересчитываются через getSolarDistance, поэтому
 * пояс всегда совпадает с план��тами при любом режиме масштаба. Нельзя брать
 * их из разброса каталога: 400 астероидов лежат от 2.17 до 28.84 а.е. — это
 * вся внутренняя система, и отступ от края уводил бы нижнюю границу в минус.
 */
export function buildBeltRanges() {
  return {
    belt: [getSolarDistance({ au: 2.1 }), getSolarDistance({ au: 3.3 })],
    kuiper: [getSolarDistance({ au: 36 }), getSolarDistance({ au: 50 })],
  };
}
