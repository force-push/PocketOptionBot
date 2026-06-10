// components/kpis.js — live KPI strip. P&L flashes/rolls on change.
import store from '../store.js';
import * as fmt from '../format.js';

export function initKpis(root) {
  const el = typeof root === 'string' ? document.querySelector(root) : root;
  if (!el) return;

  // skeleton until first data
  el.innerHTML = skeleton();

  let prevPnl = null;

  function render(kpis) {
    const meta = store.get('meta');
    if (!kpis) { el.innerHTML = skeleton(); return; }

    // Window label follows the chart's 1H/1D/1W/ALL toggle; no range = legacy "today"
    const RANGE_LABEL = { '1H': 'last hour', '1D': 'last 24h', '1W': 'last 7 days', 'ALL': 'all time' };
    const rangeSub = RANGE_LABEL[kpis.range] || 'today';
    const pnlLabel = kpis.range ? `P&amp;L (${kpis.range})` : 'Today P&amp;L';

    const pnlCls = fmt.pnlClass(kpis.today_pnl);
    const wr = fmt.pct(kpis.win_rate, 1);
    const confCls = kpis.avg_confluence >= 0.75 ? 'k-up' : '';

    const shadowPnlCls = fmt.pnlClass(kpis.shadow_pnl);

    el.innerHTML = `
      <div class="kpi">
        <div class="label">Balance</div>
        <div class="val" data-kpi="balance">${fmt.money(meta.balance ?? kpis.balance, currency(meta))}</div>
        <div class="sub">${meta.mode === 'DEMO' ? 'demo account' : 'live account'}</div>
      </div>
      <div class="kpi ${pnlCls === 'up' ? 'k-up' : pnlCls === 'down' ? 'k-down' : ''}">
        <div class="label">${pnlLabel} · Real</div>
        <div class="val ${pnlCls}" data-kpi="pnl">${fmt.pnl(kpis.today_pnl)}</div>
        <div class="sub ${pnlCls}">${fmt.pctSigned(kpis.today_pnl_pct)} · real trades only</div>
      </div>
      <div class="kpi">
        <div class="label">Win Rate · Real</div>
        <div class="val">${wr}</div>
        <div class="sub">${kpis.wins}W · ${kpis.losses}L · ${kpis.draws}D</div>
      </div>
      <div class="kpi">
        <div class="label">Traded · Real</div>
        <div class="val">${kpis.traded}</div>
        <div class="sub">${rangeSub}</div>
      </div>
      <div class="kpi">
        <div class="label">Shadows 🧪</div>
        <div class="val">${kpis.shadow_traded ?? 0}</div>
        <div class="sub ${shadowPnlCls}">P&amp;L ${fmt.pnl(kpis.shadow_pnl)}</div>
      </div>
      <div class="kpi">
        <div class="label">Skipped</div>
        <div class="val">${kpis.skipped}</div>
        <div class="sub">${rangeSub}</div>
      </div>
      <div class="kpi ${confCls}">
        <div class="label">Avg Confluence</div>
        <div class="val">${fmt.score(kpis.avg_confluence)}</div>
        <div class="sub">real · ${rangeSub}</div>
      </div>`;

    // flash the P&L cell when it changed
    const pnlEl = el.querySelector('[data-kpi="pnl"]');
    if (pnlEl && prevPnl != null && kpis.today_pnl !== prevPnl) {
      flash(pnlEl, kpis.today_pnl >= prevPnl ? 'flash-up' : 'flash-down');
    }
    prevPnl = kpis.today_pnl;
  }

  store.subscribe('kpis', render);
  store.subscribe('meta', () => render(store.get('kpis')));
}

function currency(meta) {
  return meta.currency === 'USD' || !meta.currency ? '$' : meta.currency + ' ';
}

function flash(node, cls) {
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  node.classList.remove('flash-up', 'flash-down');
  // force reflow so re-adding restarts the animation
  void node.offsetWidth;
  node.classList.add(cls);
  setTimeout(() => node.classList.remove(cls), 900);
}

function skeleton() {
  return Array.from({ length: 7 }, () => `
    <div class="kpi">
      <div class="label sk sk-line" style="width:50%"></div>
      <div class="val sk sk-line" style="width:70%;height:22px;margin-top:8px"></div>
      <div class="sub sk sk-line" style="width:40%;margin-top:6px"></div>
    </div>`).join('');
}
