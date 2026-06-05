// components/history.js — Trade History table with hover detail tooltip.
import store from '../store.js';
import * as fmt from '../format.js';

export function initHistory(rootSel, countSel) {
  const tbody = typeof rootSel === 'string' ? document.querySelector(rootSel) : rootSel;
  const countEl = countSel ? document.querySelector(countSel) : null;
  if (!tbody) return;

  // shared cursor-following tooltip
  const tip = document.createElement('div');
  tip.className = 'tooltip';
  tip.setAttribute('role', 'tooltip');
  document.body.appendChild(tip);

  let rows = [];

  function render(list) {
    rows = Array.isArray(list) ? list : [];
    if (countEl) {
      const resolved = rows.filter((r) => r.decision !== 'SKIP').length;
      countEl.textContent = `resolved · ${resolved}`;
    }
    if (!rows.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="3"><div class="empty">No trades yet</div></td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((h, i) => rowHtml(h, i)).join('');

    // clear the one-shot highlight flag after the animation runs
    const fresh = rows.filter((r) => r._new);
    if (fresh.length) {
      setTimeout(() => { fresh.forEach((r) => { delete r._new; }); }, 1600);
    }
  }

  function rowHtml(h, i) {
    const isSkip = h.decision === 'SKIP';
    const parts = fmt.pairParts(h.pair_raw);
    const dirCls = (h.dir || '').toLowerCase();
    const newCls = h._new ? ' row-new' : '';
    const skipCls = isSkip ? ' row-skip' : '';

    const resultCell = isSkip
      ? `<span class="res-sym draw" title="skipped">–</span><span class="muted" style="margin-left:7px">SKIP</span>`
      : `<span class="res-sym ${h.result || 'draw'}">${fmt.resSym(h.result)}</span>` +
        `<span class="${fmt.pnlClass(h.pnl)}" style="margin-left:7px">${fmt.pnl(h.pnl)}</span>`;

    return `<tr data-i="${i}" class="hist-row${newCls}${skipCls}">
      <td class="mono muted">${fmt.time(h.time || h.ts)}</td>
      <td>
        <span class="dir-arrow ${dirCls}" title="${h.dir || ''}">${fmt.dirSym(h.dir)}</span>
        <span class="pair">${parts.base}${parts.otc ? '<span class="otc">otc</span>' : ''}</span>
      </td>
      <td class="num">${resultCell}</td>
    </tr>`;
  }

  // --- tooltip wiring ---
  tbody.addEventListener('mouseover', (e) => {
    const tr = e.target.closest('tr.hist-row');
    if (!tr) return;
    const h = rows[+tr.dataset.i];
    if (!h) return;
    tip.innerHTML = tipHtml(h);
    tip.classList.add('show');
  });

  tbody.addEventListener('mousemove', (e) => {
    if (!tip.classList.contains('show')) return;
    const pad = 16;
    let x = e.clientX - tip.offsetWidth - pad; // prefer left of cursor (panel is on the right)
    if (x < 8) x = e.clientX + pad;
    let y = e.clientY + pad;
    if (y + tip.offsetHeight > window.innerHeight - 8) y = window.innerHeight - tip.offsetHeight - 8;
    if (y < 8) y = 8;
    tip.style.left = `${x}px`;
    tip.style.top = `${y}px`;
  });

  tbody.addEventListener('mouseleave', () => tip.classList.remove('show'));

  store.subscribe('history', render);
}

function tipHtml(h) {
  const parts = fmt.pairParts(h.pair_raw);
  const isSkip = h.decision === 'SKIP';
  const rc = h.result === 'win' ? 'up' : h.result === 'loss' ? 'down' : 'muted';
  const dir = h.dir || '';

  const head = `<div class="tt-head">
    <b>${parts.base}${parts.otc ? ' OTC' : ''}</b>
    <span class="pill ${dir.toLowerCase()}">${fmt.dirSym(dir)} ${dir}</span>
  </div>`;

  if (isSkip) {
    return head + `<div class="tt-grid">
      <span>Time</span><b class="mono">${fmt.time(h.time || h.ts)}</b>
      <span>Decision</span><b class="muted">SKIP</b>
      <span>Reason</span><b style="text-align:right">${escapeHtml(h.skip_reason || '—')}</b>
      <span>Our confluence</span><b class="mono">${fmt.score(h.our_confluence)}</b>
      <span>Bot win rate</span><b class="mono">${fmt.pct(h.bot_win_rate, 0)}</b>
    </div>`;
  }

  return head + `<div class="tt-grid">
    <span>Time</span><b class="mono">${fmt.time(h.time || h.ts)}</b>
    <span>Result</span><b class="${rc}">${(h.result || 'pending').toUpperCase()}</b>
    <span>P&amp;L</span><b class="mono ${fmt.pnlClass(h.pnl)}">${fmt.pnl(h.pnl)}</b>
    <span>Stake</span><b class="mono">${fmt.money(h.stake)}</b>
    <span>Expiry</span><b class="mono">${fmt.duration(h.expiry_seconds)}</b>
    <span>Our confluence</span><b class="mono">${fmt.score(h.our_confluence)}</b>
    <span>Bot win rate</span><b class="mono">${fmt.pct(h.bot_win_rate, 0)}</b>
    <span>Entry price</span><b class="mono">${fmt.entryPrice(h.entry)}</b>
  </div>`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}
