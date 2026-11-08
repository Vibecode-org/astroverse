import { describe, expect, test } from 'vitest';
import * as THREE from 'three';
import { lodLevel, screenRadius, focalLength } from '../src/scene/lodManager.js';
import { equatorialXYZ, galacticXYZ, SUN_GALACTIC, GALAXY_SCALE } from '../src/bodies/utils/coordinates.js';
import { safeColor, colorSeed, rgba, FALLBACK_COLOR } from '../src/bodies/utils/colorUtils.js';
import { hashUnit } from '../src/bodies/utils/hash.js';
import { makeSeededRng } from '../src/bodies/utils/rng.js';
import { kindLabel, objectScale } from '../src/bodies/utils/celestialUtils.js';
import { formatLy, formatNum, formatPeriod } from '../src/utils/formatUtils.js';
import { orbitFrame, orbitPhase, placeOnOrbit, getLocalOrbitRadius,
  makeOrbit, makeAsteroidBelt, makeKuiperBelt } from '../src/bodies/helpers/orbitHelpers.js';

describe('LOD boundaries and hysteresis', () => {
  test.each([
    [-1, 0, 0], [-1, 2.99, 0], [-1, 3, 1], [-1, 12, 2],
    [1, 1.99, 0], [1, 2, 1], [1, 11.99, 1], [1, 12, 2],
    [2, 1.99, 0], [2, 2, 1], [2, 7.99, 1], [2, 8, 2],
  ])('previous %s radius %s -> %s', (prev, radius, expected) => {
    expect(lodLevel(radius, prev)).toBe(expected);
  });
  test('projection scales with viewport and distance, including camera inside body', () => {
    expect(focalLength({ fov: 90 }, 1000)).toBeCloseTo(500);
    expect(screenRadius(2, 10, 500)).toBe(100);
    expect(screenRadius(2, 0, 500)).toBe(10000000);
  });
});

test('physical catalog positions map deterministically into each display frame', () => {
  expect(equatorialXYZ({ ra: 0, dec: 0, distance_ly: 10 }).y).toBe(0);
  expect(equatorialXYZ({ ra: 6, dec: 90, distance_ly: 10 }).y).toBeGreaterThan(9);
  expect(equatorialXYZ({}).length()).toBeGreaterThan(0);
  expect(galacticXYZ({ gx: 1, gy: 2, gz: 3 }).toArray()).toEqual([1, 2, 3]);
  expect(galacticXYZ({ gx: 0 }).toArray()).toEqual([0, 0, 0]);
  expect(galacticXYZ({ galactic_l: 0, galactic_b: 0, distance_ly: 100 }).x)
    .toBeCloseTo(SUN_GALACTIC.x + 100 * GALAXY_SCALE);
  expect(galacticXYZ({}).toArray().every(Number.isFinite)).toBe(true);
});

test('hex helpers handle every supported CSS length and malformed metadata', () => {
  for (const color of ['#abc', '#abcd', '#AABBCC', '#11223344', ' #123456 ']) {
    expect(safeColor(color)).toBe(color.trim());
    expect(Number.isFinite(colorSeed(color))).toBe(true);
    expect(rgba(color, 0.5)).toMatch(/^rgba\(\d+,\d+,\d+,0.5\)$/);
  }
  for (const bad of [null, undefined, {}, 12, 'red', '#12345', '#gggggg']) {
    expect(safeColor(bad)).toBe(FALLBACK_COLOR);
    expect(safeColor(bad, '#ffffff')).toBe('#ffffff');
    expect(rgba(bad, 1)).toBe('rgba(159,180,255,1)');
  }
  expect(colorSeed('#abc')).toBe(0xaabbcc);
});

test('seeded random streams and hash values are repeatable and bounded', () => {
  for (const seed of ['earth', 'Земля', 0, 123]) {
    const a = makeSeededRng(seed), b = makeSeededRng(seed);
    for (let i = 0; i < 100; i++) {
      const n = a();
      expect(n).toBe(b()); expect(n).toBeGreaterThanOrEqual(0); expect(n).toBeLessThan(1);
    }
  }
  expect(hashUnit('a')).toBe(hashUnit('a'));
  expect(hashUnit('a')).not.toBe(hashUnit('b'));
});

test('object scales and labels cover all kinds and unknown kinds', () => {
  const kinds = { star: 'local', planet: 'solar', dwarf_planet: 'solar', moon: 'solar',
    asteroid: 'solar', comet: 'solar', exoplanet: 'local', galaxy: 'galaxy',
    nebula: 'galaxy', cluster: 'galaxy', black_hole: 'galaxy' };
  for (const [kind, scale] of Object.entries(kinds)) {
    expect(objectScale({ kind })).toBe(scale);
    expect(kindLabel(kind)).not.toBe(kind);
  }
  expect(objectScale({ kind: 'star', id: 'sun' })).toBe('solar');
  expect(objectScale({ kind: 'star', scale: 'galaxy' })).toBe('galaxy');
  expect(kindLabel('unknown')).toBe('unknown');
});

test('display formatting changes units at exact boundaries', () => {
  expect(formatLy(1)).toBe('1 св. лет'); expect(formatLy(1000)).toBe('1.0 тыс. св. лет');
  expect(formatLy(10000)).toBe('10 тыс. св. лет'); expect(formatLy(1e6)).toBe('1.00 млн св. лет');
  expect(formatNum(1e6)).toBe('1.00e+6'); expect(formatNum(12)).toBe('12');
  expect(formatPeriod(1)).toBe('24.0 ч'); expect(formatPeriod(2)).toBe('2.0 сут');
  expect(formatPeriod(365.25)).toBe('1.0 лет');
});

test('orbit basis is orthonormal and time reversal returns the same position at the same date', () => {
  const center = new THREE.Vector3(10, 20, 30), frame = orbitFrame('host');
  expect(frame.x.length()).toBeCloseTo(1); expect(frame.y.length()).toBeCloseTo(1);
  expect(frame.x.dot(frame.y)).toBeCloseTo(0);
  const at = t => placeOnOrbit(new THREE.Vector3(), center, frame, 5, orbitPhase('planet') + t);
  expect(at(0).distanceTo(center)).toBeCloseTo(5);
  expect(at(2 * Math.PI).distanceTo(at(0))).toBeLessThan(1e-12);
  for (const bad of [undefined, null, 0, -1, NaN, Infinity, '1'])
    expect(getLocalOrbitRadius({ au: bad })).toBeCloseTo(1.26);
  expect(getLocalOrbitRadius({ au: 1 }, 2)).toBeGreaterThan(4);
  expect(getLocalOrbitRadius({ au: 100 }, 2)).toBe(getLocalOrbitRadius({ au: 8 }, 2));
});

test('orbits and belts build reproducible buffers', () => {
  expect(makeOrbit(5).geometry.attributes.position.count).toBe(257);
  for (const make of [makeAsteroidBelt, makeKuiperBelt]) {
    const a = make(), b = make();
    expect(a.children[0].geometry.attributes.position.array)
      .toEqual(b.children[0].geometry.attributes.position.array);
    expect(make([10, 10]).children[0].geometry.attributes.position.count).toBeGreaterThan(0);
  }
});
