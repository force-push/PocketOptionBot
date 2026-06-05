// components/active.js — Active Trades cards.
// Countdown bars tick locally each second from expiry_at; cards flash and
// auto-remove on resolve.
import store from '../store.js';
import * as fmt from '../format.js';

export function initActive(rootSel, countSel) {
  const list = typeof rootSel === 'string' ? document.querySelector(rootSel) : rootSel;
  const countEl = countSel ? document.querySelector(countSel) : null;
  if (!list) return;

  let trades = [];

  function render(active) {
    trades = Array.isArray(active) ? active : [];
    if (countEl) countEl.textContent = `${trades.length} open`;
    if (!trades.length) {
      list.innerHTML = `<div class="empty">No active trades</div>`;
      return;
    }
    // keep existing card nodes where possible (so flashes aren't clobbered)
    list.innerHTML = trades.map((t) => cardHtml(t)).join('');
    tick(); // immediate paint of countdowns
  }

  function cardHtml(a) {
    const parts = fmt.pairParts(a.pair_raw);
    const dirCls = (a.dir || '').toLowerCase();
    const n = a.confluence_n || 0;
    const conf = Array.from({ length: 5 }, (_, i) => `<i class="${i < n ? 'on' : ''}"></i>`).join('');
    return `<div class="trade-card" data-id="${a.trade_id}">
      <div class="row">
        <div>
          <div class="pair">${parts.base}${parts.otc ? '<span class="otc">otc</span>' : ''}
            &nbsp;<span class="pill ${dirCls}">${a.dir}</span></div>
          <div class="meta">entry ${fmt.entryPrice(a.entry)} · ${fmt.duration(a.expiry_seconds)} expiry</div>
        </div>
        <div style="text-align:right">
          <div class="stake">${fmt.money(a.stake)}</div>
          <div class="meta">at risk</div>
        </div>
      </div>
      <div class="countdown">
        <div class="track"><div class="fill" data-fill></div></div>
        <div class="t"><span data-left>—</span><span>${n}/5 signals</span></div>
      </div>
      <div class="conf-bar">${conf}</div>
    </div>`;
  }

  // local per-second ticker — drives all visible countdown bars
  function tick() {
    const now = Date.now();
    for (const a of trades) {
      const card = list.querySelector(`.trade-card[data-id="${cssEscape(a.trade_id)}"]`);
      if (!card) continue;
      const total = a.expiry_seconds || 30;
      const left = fmt.secondsUntil(a.expiry_at, now);
      const pct = Math.max(0, Math.min(100, (left / total) * 100));
      const fill = card.querySelector('[data-fill]');
      const leftEl = card.querySelector('[data-left]');
      if (fill) {
        fill.style.width = `${pct}%`;
        fill.classList.toggle('urgent', left <= 5);
      }
      if (leftEl) leftEl.textContent = `${Math.ceil(left)}s remaining`;
    }
  }

  setInterval(tick, 1000);

  // resolve flash + auto-remove. Listen on a custom event from main.js
  list.addEventListener('trade:resolve', (e) => {
    const id = e.detail && e.detail.trade_id;
    const card = id && list.querySelector(`.trade-card[data-id="${cssEscape(id)}"]`);
    if (!card) { store.removeActive(id); return; }
    const won = e.detail.result === 'win';
    card.classList.add(won ? 'resolved-win' : 'resolved-loss');
    setTimeout(() => store.removeActive(id), 850);
  });

  store.subscribe('active', render);
}

function cssEscape(s) {
  if (window.CSS && CSS.escape) return CSS.escape(s);
  return String(s).replace(/["\\]/g, '\\$&');
}
