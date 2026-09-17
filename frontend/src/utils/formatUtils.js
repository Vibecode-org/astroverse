export function formatLy(ly) {
  if (ly >= 1e6) return `${(ly / 1e6).toFixed(2)} млн св. лет`;
  if (ly >= 1000) return `${(ly / 1000).toFixed(ly >= 10000 ? 0 : 1)} тыс. св. лет`;
  return `${ly} св. лет`;
}

export function formatNum(n) {
  if (n >= 1e6) return n.toExponential(2);
  return new Intl.NumberFormat('ru-RU').format(n);
}

export function formatPeriod(days) {
  if (days >= 365) return `${(days / 365.25).toFixed(1)} лет`;
  if (days >= 2) return `${days.toFixed(1)} сут`;
  return `${(days * 24).toFixed(1)} ч`;
}