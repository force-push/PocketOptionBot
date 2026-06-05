// store.js — tiny in-memory state container with pub/sub.
// Components subscribe to a topic; producers (api/ws) patch slices.

const state = {
  meta: { mode: 'DEMO', dry_run: true, connected: false, balance: null, currency: 'USD' },
  kpis: null,
  active: [],          // array of active trade objects
  history: [],          // newest-first history rows
  performance: null,    // { range, equity[], winloss, by_pair }
  settings: null,       // grouped settings payload
  ws: 'connecting',     // connecting | live | reconnecting | closed
  demo: false,          // running on bundled sample data (no backend)
};

const subs = new Map(); // topic -> Set<fn>

/** Subscribe to a topic; returns an unsubscribe fn. Fires immediately with current value. */
export function subscribe(topic, fn) {
  if (!subs.has(topic)) subs.set(topic, new Set());
  subs.get(topic).add(fn);
  // immediate push of current value so late subscribers render
  try { fn(get(topic)); } catch (e) { /* ignore */ }
  return () => subs.get(topic)?.delete(fn);
}

function emit(topic) {
  const set = subs.get(topic);
  if (!set) return;
  const value = get(topic);
  for (const fn of set) {
    try { fn(value); } catch (e) { console.error('[store] subscriber error', topic, e); }
  }
}

/** Read a slice by topic. */
export function get(topic) {
  return topic ? state[topic] : state;
}

/* ---- mutators (each emits its topic, plus 'any' for global listeners) ---- */

export function setMeta(patch) {
  Object.assign(state.meta, patch);
  emit('meta');
}

export function setKpis(kpis) {
  state.kpis = kpis;
  emit('kpis');
}

export function setActive(list) {
  state.active = Array.isArray(list) ? list.slice() : [];
  emit('active');
}

/** Add or replace one active trade by trade_id. */
export function upsertActive(trade) {
  const id = trade.trade_id;
  const idx = state.active.findIndex((t) => t.trade_id === id);
  if (idx >= 0) state.active[idx] = trade;
  else state.active = [...state.active, trade];
  emit('active');
}

/** Remove an active trade by id (e.g. on resolve). */
export function removeActive(id) {
  const before = state.active.length;
  state.active = state.active.filter((t) => t.trade_id !== id);
  if (state.active.length !== before) emit('active');
}

export function setHistory(rows) {
  state.history = Array.isArray(rows) ? rows.slice() : [];
  emit('history');
}

/** Prepend a freshly-resolved/new row (newest first), flagged for highlight. */
export function prependHistory(row) {
  const flagged = { ...row, _new: true };
  // de-dupe by trade_id when present
  if (row.trade_id) {
    state.history = state.history.filter((r) => r.trade_id !== row.trade_id);
  }
  state.history = [flagged, ...state.history];
  emit('history');
}

export function setPerformance(perf) {
  state.performance = perf;
  emit('performance');
}

export function setSettings(s) {
  state.settings = s;
  emit('settings');
}

export function setWsStatus(status) {
  if (state.ws === status) return;
  state.ws = status;
  emit('ws');
}

export function setDemo(on) {
  state.demo = !!on;
  emit('demo');
}

export const store = {
  subscribe, get,
  setMeta, setKpis,
  setActive, upsertActive, removeActive,
  setHistory, prependHistory,
  setPerformance, setSettings,
  setWsStatus, setDemo,
};

export default store;
