// api.js — REST client for the dashboard backend (§4.2). Token-aware.
//
// The optional DASHBOARD_TOKEN is required for POST /api/settings when the
// server has one configured. We read it from (in order): a <meta name=
// "dashboard-token"> tag, localStorage, or the URL hash query (?token=...).

const BASE = ''; // same-origin

function readToken() {
  try {
    const meta = document.querySelector('meta[name="dashboard-token"]');
    if (meta && meta.content && meta.content !== '{{TOKEN}}') return meta.content;
    const ls = localStorage.getItem('dashboard_token');
    if (ls) return ls;
    const m = location.search.match(/[?&]token=([^&]+)/);
    if (m) return decodeURIComponent(m[1]);
  } catch (e) { /* ignore */ }
  return null;
}

/** Persist a token for subsequent writes. */
export function setToken(tok) {
  try { tok ? localStorage.setItem('dashboard_token', tok) : localStorage.removeItem('dashboard_token'); }
  catch (e) { /* ignore */ }
}

/** Current dashboard token (if any) — used to authorise the WebSocket too. */
export function getToken() {
  return readToken();
}

function headers(extra = {}) {
  const h = { Accept: 'application/json', ...extra };
  const tok = readToken();
  if (tok) h['Authorization'] = `Bearer ${tok}`;
  return h;
}

async function req(path, opts = {}, { timeout = 15000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const res = await fetch(BASE + path, { ...opts, signal: ctrl.signal, headers: headers(opts.headers) });
    const text = await res.text();
    let body = null;
    if (text) { try { body = JSON.parse(text); } catch (e) { body = text; } }
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  /** GET /api/state — KPI + active snapshot. */
  state: () => req('/api/state'),

  /** GET /api/history?limit&before */
  history: ({ limit = 100, before = null } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (before) q.set('before', before);
    return req(`/api/history?${q.toString()}`);
  },

  /** GET /api/performance?range=1H|1D|1W|ALL */
  performance: (range = '1D') => req(`/api/performance?range=${encodeURIComponent(range)}`),

  /** GET /api/analysis?window=SINCE5AM|ALL — breakdown tables. */
  analysis: (window = 'SINCE5AM') => req(`/api/analysis?window=${encodeURIComponent(window)}`),

  /** GET /api/settings — grouped, masked. */
  settings: () => req('/api/settings'),

  /**
   * POST /api/settings — partial update.
   * @param {Object} fields  changed field map
   * @param {boolean} confirmLive  required when flipping to LIVE
   */
  saveSettings: (fields, confirmLive = false) => req('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fields, confirm_live: confirmLive }),
  }),
};

export default api;
