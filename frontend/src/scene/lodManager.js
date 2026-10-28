/** LOD-менеджер: трёхуровневый рендер объектов каталога.
 *
 * Уровни:
 *   L0 (far)  — один THREE.Points на все объекты, 1 draw call
 *   L1 (mid)  — InstancedMesh на вид, ~5–10 draw calls
 *   L2 (near) — индивидуальные детальные меши, единицы draw calls
 *
 * Переключение по угловому размеру объекта на экране (экранный радиус в пикселях).
 * Гистерезис: порог входа ≠ порога выхода, чтобы не было дithering между уровнями.
 * Плавное появление: fade по альфе при приближении.
 */

import * as THREE from 'three';
import { hashUnit } from '../bodies/utils/hash.js';

// Пороги углового радиуса в пикселях.
// Объект с экранным радиусом < L1_EXIT считается далёким (L0).
// Объект с экранным радиусом >= L1_ENTER считается средним (L1).
// Объект с экранным радиусом >= L2_ENTER считается близким (L2).
// Гистерезис: выход с уровня происходит при меньшем радиусе, чем вход.
export const LOD_THRESHOLDS = {
  // L0 -> L1: вход в L1 при экранном радиусе >= 3 px, выход в L0 при < 2 px
  L1_ENTER: 3.0,
  L1_EXIT: 2.0,
  // L1 -> L2: вход в L2 при экранном радиусе >= 12 px, выход в L1 при < 8 px
  L2_ENTER: 12.0,
  L2_EXIT: 8.0,
};

/** Определяет уровень LOD для объекта с учётом гистерезиса.
 *
 * @param {number} sr — экранный радиус в пикселях
 * @param {number} prevLevel — предыдущий уровень (0, 1, 2) или -1 если неизвестен
 * @returns {number} новый уровень (0, 1, 2)
 */
export function lodLevel(sr, prevLevel) {
  // L2: близко
  if (prevLevel === 2) {
    if (sr < LOD_THRESHOLDS.L2_EXIT) return 1;
    return 2;
  }
  if (sr >= LOD_THRESHOLDS.L2_ENTER) return 2;

  // L1: средняя дистанция
  if (prevLevel === 1) {
    if (sr < LOD_THRESHOLDS.L1_EXIT) return 0;
    if (sr >= LOD_THRESHOLDS.L2_ENTER) return 2;
    return 1;
  }
  // prevLevel === 0 или -1
  if (sr >= LOD_THRESHOLDS.L1_ENTER) {
    if (sr >= LOD_THRESHOLDS.L2_ENTER) return 2;
    return 1;
  }
  return 0;
}

/** Коэффициент альфа-фади для плавного появления при переходе между уровнями.
 *
 * Возвращает значение в [0, 1]. На пороге входа alpha = 0, на пороге выхода alpha = 1.
 * Для L0 (самый дальний уровень) фади не нужен — точки всегда видны.
 */
export function fadeAlpha(sr, level, enterThreshold, exitThreshold) {
  if (level === 0) return 1.0;
  // Фади только при входе на уровень: от enterThreshold до exitThreshold
  if (sr <= enterThreshold) return 0.0;
  if (sr >= exitThreshold) return 1.0;
  return (sr - enterThreshold) / (exitThreshold - enterThreshold);
}

/** Детерминированный цвет объекта из его id (K-5: без Math.random). */
export function objectColor(obj) {
  const h = hashUnit(obj.id);
  // Оттенок по хешу, насыщенность и яркость в узком диапазоне для реалистичности.
  const hue = h * 360;
  const sat = 0.4 + h * 0.4;
  const light = 0.5 + h * 0.3;
  const color = new THREE.Color().setHSL(hue / 360, sat, light);
  return color;
}

/** Детерминированный размер точки для L0 из id объекта. */
export function pointSize(obj, baseSize) {
  const h = hashUnit(obj.id + ':size');
  return baseSize * (0.7 + h * 0.6);
}
