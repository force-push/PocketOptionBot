// format.js — pure formatters (no DOM, no side effects). Unit-testable.

/** Format a signed P&L value as currency, e.g. +$1.38 / -$1.50 / $0.00 */
export function pnl(v, currency = '$') {
  if (v == null || Number.isNaN(v)) return '—';
  const n = Number(v);
  if (n > 0) return `+${currency}${n.toFixed(2)}`;
  if (n < 0) return `-${currency}${Math.abs(n).toFixed(2)}`;
  return `${currency}0.00`;
}

/** CSS class describing a signed value's direction. */
export function pnlClass(v) {
  if (v == null || Number.isNaN(v)) return 'muted';
  const n = Number(v);
  return n > 0 ? 'up' : n < 0 ? 'down' : 'muted';
}

/** Format a plain money amount (unsigned), e.g. $1,184.50 */
export function money(v, currency = '$') {
  if (v == null || Number.isNaN(v)) return '—';
  return currency + Number(v).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Format a 0..1 ratio as a percent string, e.g. 0.614 -> "61.4%" */
export function pct(v, digits = 1) {
  if (v == null || Number.isNaN(v)) return '—';
  return `${(Number(v) * 100).toFixed(digits)}%`;
}

/** Format an already-percent number, e.g. 3.71 -> "▲ 3.71%" with a directional arrow. */
export function pctSigned(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  const n = Number(v);
  const arrow = n > 0 ? '▲' : n < 0 ? '▼' : '·';
  return `${arrow} ${Math.abs(n).toFixed(digits)}%`;
}

/** A fixed-precision score, e.g. 0.81 */
export function score(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '—';
  return Number(v).toFixed(digits);
}

/** HH:MM:SS local time from an ISO timestamp (or pass through a time-string). */
export function time(iso) {
  if (!iso) return '—';
  // already a HH:MM:SS string?
  if (/^\d{2}:\d{2}(:\d{2})?$/.test(iso)) return iso;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('en-GB', { hour12: false });
}

/** Short clock label HH:MM for chart axes. */
export function clock(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleTimeString('en-GB', { hour12: false, hour: '2-digit', minute: '2-digit' });
}

/** Whole-second duration label, e.g. 30 -> "30s"; clamps negatives to 0. */
export function duration(seconds) {
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}m ${r}s` : `${m}m`;
}

/** Seconds remaining until an ISO epoch, clamped at 0. */
export function secondsUntil(iso, now = Date.now()) {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 0;
  return Math.max(0, (t - now) / 1000);
}

/** Direction arrow symbol. */
export function dirSym(dir) {
  return dir === 'CALL' ? '▲' : dir === 'PUT' ? '▼' : '·';
}

/** Result symbol: win ✓ / loss ✗ / draw – . */
export function resSym(result) {
  if (result === 'win') return '✓';
  if (result === 'loss') return '✗';
  return '–';
}

/** Pair label parts: { base, otc } from raw "EUR/USD OTC". */
export function pairParts(raw) {
  if (!raw) return { base: '—', otc: false };
  const isOtc = /otc/i.test(raw);
  const base = raw.replace(/\s*otc\s*/i, '').trim();
  return { base, otc: isOtc };
}

/** Format an entry price preserving its precision (numbers and strings). */
export function entryPrice(v) {
  if (v == null || v === '') return '—';
  return String(v);
}
