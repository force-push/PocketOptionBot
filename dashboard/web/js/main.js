// main.js — bootstrap, hash router, WS + REST wiring, demo-mode fallback.
import store from './store.js';
import api from './api.js';
import { ReconnectingWS } from './ws.js';
import * as fmt from './format.js';

import { initKpis } from './components/kpis.js';
import { initHistory } from './components/history.js';
import { initActive } from './components/active.js';
import { initPerformance } from './components/performance.js';
import { initSettings } from './components/settings.js';

let currentRange = '1D';
let ws = null;
let demoSim = null;

/* ------------------------------------------------------------------ */
/* Tab routing (hash router)                                          */
/* ------------------------------------------------------------------ */
function initRouter() {
  const tabs = Array.from(document.querySelectorAll('.tab'));
  const views = Array.from(document.querySelectorAll('.view'));

  function show(name) {
    const valid = views.some((v) => v.id === `view-${name}`);
    const target = valid ? name : 'monitoring';
    tabs.forEach((t) => {
      const on = t.dataset.view === target;
      t.classList.toggle('active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    views.forEach((v) => v.classList.toggle('active', v.id === `view-${target}`));
  }

  tabs.forEach((t) => {
    t.addEventListener('click', () => { location.hash = t.dataset.view; });
    t.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const i = tabs.indexOf(t);
        const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
        next.focus();
        location.hash = next.dataset.view;
      }
    });
  });

  window.addEventListener('hashchange', () => show(location.hash.replace('#', '')));
  show(location.hash.replace('#', '') || 'monitoring');
}

/* ------------------------------------------------------------------ */
/* Top-bar status chips                                               */
/* ------------------------------------------------------------------ */
function initChips() {
  const wsChip = document.getElementById('chip-ws');
  const balChip = document.getElementById('chip-balance');
  const modeChip = document.getElementById('chip-mode');

  store.subscribe('ws', (status) => {
    if (!wsChip) return;
    const map = {
      connecting: ['connecting', 'WS Connecting…'],
      live: ['live', store.get('demo') ? 'Demo Mode' : 'WS Connected'],
      reconnecting: ['reconnecting', 'Reconnecting…'],
      closed: ['closed', 'WS Closed'],
    };
    const [cls, label] = map[status] || map.connecting;
    wsChip.className = `chip ws-${cls}`;
    wsChip.innerHTML = `<span class="live-dot"></span>${label}`;
  });

  store.subscribe('meta', (meta) => {
    if (balChip) balChip.querySelector('b').textContent = fmt.money(meta.balance, meta.currency === 'USD' ? '$' : '$');
    if (modeChip) {
      const live = meta.mode === 'LIVE';
      modeChip.className = `chip ${live ? 'badge-live' : 'badge-demo'}`;
      modeChip.textContent = `● ${meta.mode}${meta.dry_run ? ' · DRY' : ''}`;
    }
  });
}

/* ------------------------------------------------------------------ */
/* Apply a /api/state (or ws state) snapshot to the store            */
/* ------------------------------------------------------------------ */
function applyState(s) {
  if (!s) return;
  store.setMeta({
    mode: s.mode, dry_run: s.dry_run, connected: s.connected,
    balance: s.balance, currency: s.currency,
  });
  if (s.kpis) store.setKpis(s.kpis);
  if (Array.isArray(s.active)) store.setActive(s.active);
}

/* ------------------------------------------------------------------ */
/* WebSocket message dispatch                                        */
/* ------------------------------------------------------------------ */
function onWsMessage(type, data) {
  switch (type) {
    case 'hello':
      if (data && data.mode) store.setMeta({ mode: data.mode });
      break;
    case 'state':
      applyState(data);
      break;
    case 'trade_opened':
      store.upsertActive(data);
      break;
    case 'trade_resolved': {
      // flash + remove the matching active card, then prepend to history
      const list = document.getElementById('active-list');
      if (list && data.trade_id) {
        list.dispatchEvent(new CustomEvent('trade:resolve', { detail: data }));
      } else if (data.trade_id) {
        store.removeActive(data.trade_id);
      }
      store.prependHistory(data);
      if (typeof data.balance_after === 'number') store.setMeta({ balance: data.balance_after });
      refreshPerformance();
      break;
    }
    case 'history':
      store.prependHistory(data);
      break;
    case 'settings_changed':
      // backend pushed a settings change; refresh the form payload
      loadSettings();
      break;
    default:
      break;
  }
}

/* ------------------------------------------------------------------ */
/* REST loaders                                                      */
/* ------------------------------------------------------------------ */
async function loadHistory() {
  try {
    const h = await api.history({ limit: 100 });
    store.setHistory(h.rows || h || []);
  } catch (e) { /* demo fallback handled by caller */ throw e; }
}

async function refreshPerformance() {
  try {
    const p = store.get('demo') ? await loadSample('performance.json') : await api.performance(currentRange);
    p.range = currentRange;
    store.setPerformance(p);
  } catch (e) { console.warn('[perf] failed', e); }
}

async function loadSettings() {
  try {
    const s = store.get('demo') ? await loadSample('settings.json') : await api.settings();
    store.setSettings(s);
  } catch (e) { console.warn('[settings] load failed', e); }
}

/* ------------------------------------------------------------------ */
/* Demo mode — bundled samples + a simulated tick                    */
/* ------------------------------------------------------------------ */
async function loadSample(name) {
  const res = await fetch(new URL(`../sample/${name}`, import.meta.url));
  if (!res.ok) throw new Error(`sample ${name} ${res.status}`);
  return res.json();
}

async function enterDemoMode() {
  console.info('[dashboard] backend unreachable — entering demo mode (bundled samples).');
  store.setDemo(true);
  store.setWsStatus('live'); // chip shows "Demo Mode"

  const [state, history, perf, settings] = await Promise.all([
    loadSample('state.json'),
    loadSample('history.json'),
    loadSample('performance.json'),
    loadSample('settings.json'),
  ]);

  // re-base the sample active trades so countdowns are live from "now"
  const now = Date.now();
  state.active = (state.active || []).map((t, i) => {
    const total = t.expiry_seconds || 30;
    const left = Math.max(8, total - i * 6);
    return { ...t, opened_at: new Date(now - (total - left) * 1000).toISOString(), expiry_at: new Date(now + left * 1000).toISOString() };
  });

  applyState(state);
  store.setHistory(history.rows || []);
  perf.range = currentRange;
  store.setPerformance(perf);
  store.setSettings(settings);

  startDemoSim();
}

// A light simulator: resolves an active trade when its countdown ends,
// prepends a history row, nudges balance/P&L, and occasionally opens a new one.
function startDemoSim() {
  if (demoSim) clearInterval(demoSim);
  const pairs = [
    { raw: 'EUR/USD OTC', api: 'EURUSD_otc', entry: 1.07432 },
    { raw: 'GBP/JPY OTC', api: 'GBPJPY_otc', entry: 188.214 },
    { raw: 'USD/CHF', api: 'USDCHF', entry: 0.89744 },
    { raw: 'AUD/CAD OTC', api: 'AUDCAD_otc', entry: 0.90112 },
  ];
  let counter = 1000;

  demoSim = setInterval(() => {
    const now = Date.now();
    const active = store.get('active');

    // resolve any expired trade
    for (const t of active) {
      if (fmt.secondsUntil(t.expiry_at, now) <= 0) {
        const win = Math.random() < 0.6;
        const draw = Math.random() < 0.05;
        const result = draw ? 'draw' : win ? 'win' : 'loss';
        const payout = 0.92;
        const pnl = result === 'win' ? +(t.stake * payout).toFixed(2) : result === 'loss' ? -t.stake : 0;
        const meta = store.get('meta');
        const balance_after = +((meta.balance || 0) + pnl).toFixed(2);
        const row = {
          ts: new Date(now).toISOString(), time: fmt.time(new Date(now).toISOString()),
          pair_raw: t.pair_raw, pair_api: t.pair_api, otc: /otc/i.test(t.pair_raw),
          dir: t.dir, decision: 'TRADE', result, pnl, stake: t.stake,
          expiry_seconds: t.expiry_seconds, our_confluence: t.confluence_score,
          bot_win_rate: 0.84, entry: t.entry, skip_reason: null, trade_id: t.trade_id,
          balance_after,
        };
        onWsMessage('trade_resolved', row);
        bumpKpis(result, pnl, balance_after);
      }
    }

    // occasionally open a new trade to keep the panel alive
    if (store.get('active').length < 3 && Math.random() < 0.4) {
      const p = pairs[Math.floor(Math.random() * pairs.length)];
      const dir = Math.random() < 0.5 ? 'CALL' : 'PUT';
      const exp = Math.random() < 0.5 ? 30 : 60;
      const n = 3 + Math.floor(Math.random() * 3);
      counter += 1;
      onWsMessage('trade_opened', {
        trade_id: `sim-${counter}`, pair_raw: p.raw, pair_api: p.api, dir,
        stake: 1.5, entry: p.entry, opened_at: new Date(now).toISOString(),
        expiry_at: new Date(now + exp * 1000).toISOString(), expiry_seconds: exp,
        confluence_n: n, confluence_score: +(0.75 + Math.random() * 0.18).toFixed(2),
      });
    }
  }, 1000);
}

function bumpKpis(result, pnl, balance) {
  const k = store.get('kpis');
  if (!k) return;
  const next = { ...k };
  if (result === 'win') next.wins += 1;
  else if (result === 'loss') next.losses += 1;
  else next.draws += 1;
  next.trades_today += 1;
  next.traded += 1;
  next.today_pnl = +(next.today_pnl + pnl).toFixed(2);
  const total = next.wins + next.losses + next.draws;
  next.win_rate = total ? next.wins / total : 0;
  next.active_count = store.get('active').length;
  next.at_risk = +(next.active_count * 1.5).toFixed(2);
  store.setKpis(next);
  store.setMeta({ balance });
}

/* ------------------------------------------------------------------ */
/* Boot                                                              */
/* ------------------------------------------------------------------ */
async function boot() {
  initRouter();
  initChips();
  initKpis('#kpi-strip');
  initHistory('#history-rows', '#history-count');
  initActive('#active-list', '#active-count');
  initPerformance({
    chartSel: '#chart-wrap',
    segSel: '#perf-seg',
    winlossSel: '#winloss',
    onRange: (r) => { currentRange = r; refreshPerformance(); },
  });
  initSettings({ rootSel: '#settings-wrap' });

  store.setWsStatus('connecting');

  // Try the live backend first; on any failure fall back to demo mode.
  let live = false;
  try {
    const state = await api.state();
    applyState(state);
    live = true;
  } catch (e) {
    live = false;
  }

  if (!live) {
    await enterDemoMode();
    return;
  }

  // backend reachable — load the rest and open the websocket
  await Promise.allSettled([loadHistory(), refreshPerformance(), loadSettings()]);

  ws = new ReconnectingWS('/ws', {
    onStatus: (s) => store.setWsStatus(s),
    onMessage: onWsMessage,
  });
  ws.connect();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}
