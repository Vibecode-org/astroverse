/** Parsing helpers for catalog `color` values.
 *
 * The same tiny parser was duplicated in three texture modules, and every copy
 * assumed a well-formed `#rrggbb` string. It is a crash site: `addColorStop`
 * throws `DOMException: SyntaxError` on an unparseable CSS colour, and the throw
 * happens inside the scene build, leaving a permanently blank canvas with no
 * recoverable UI. `validate_catalog` now rejects malformed colours at the
 * source, but these helpers stay defensive because a single bad value must
 * never be able to take down the whole scene.
 */

/** Used whenever a colour is missing or unparseable. */
export const FALLBACK_COLOR = '#9fb4ff';

const HEX_PATTERN = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$/;

/** Return `value` if it is a parseable hex colour, otherwise `fallback`. */
export function safeColor(value, fallback = FALLBACK_COLOR) {
  return typeof value === 'string' && HEX_PATTERN.test(value.trim()) ? value.trim() : fallback;
}

/** Expand a validated 3/4/6/8-digit hex colour to 6 or 8 digits.
 *
 * `#abc` / `#abcd` are valid CSS and valid catalog values, but the numeric
 * helpers below need byte-aligned channels; slicing a 4-digit value produced
 * a negative/NaN shift before. */
function expandHex(value, fallback) {
  const hex = safeColor(value, fallback).slice(1);
  if (hex.length === 3 || hex.length === 4) {
    return hex.split('').map((ch) => ch + ch).join('');
  }
  return hex;
}

/** 24-bit RGB integer for a hex colour, or 1 for anything unparseable. */
export function colorSeed(value) {
  const parsed = parseInt(expandHex(value).slice(0, 6), 16);
  return Number.isFinite(parsed) ? parsed : 1;
}

/** `rgba(r,g,b,a)` string for a hex colour, never an unparseable CSS value. */
export function rgba(value, alpha, fallback = FALLBACK_COLOR) {
  const hex = expandHex(value, fallback);
  const r = parseInt(hex.slice(0, 2), 16);
  const g = parseInt(hex.slice(2, 4), 16);
  const b = parseInt(hex.slice(4, 6), 16);
  return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
}
