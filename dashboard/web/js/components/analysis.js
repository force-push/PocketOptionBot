// analysis.js — Analysis tab: breakdown tables from /api/analysis.
// Win rates are coloured against the 92%-payout break-even (52.17%).
import api from '../api.js';
import * as fmt from '../format.js';

let root = null;
let currentWindow = 'SINCE5AM';
let loaded = false;

function wrCell(d) {
  if (d.wr === null || d.wr === undefined) return '<td class="num">—</td>';
  const pctTxt = (d.wr * 100).toFixed(1) + '%';
  const cls = d.edge ? 'wr-edge' : 'wr-below';
  return `<td class="num ${cls}">${pctTxt}</td>`;
}

function pnlCell(d) {
  if (d.pnl === null || d.pnl === undefined) return '<td class="num">—</td>';
  return `<td class="num ${fmt.pnlClass(d.pnl)}">${fmt.pnl(d.pnl)}</td>`;
}

function table(title, rows, { hidePnl = false, note = '' } = {}) {
  if (!rows || !rows.length) {
    return `<div class="an-card"><h4>${title}</h4><p class="an-empty">No data.</p></div>`;
  }
  const body = rows.map((d) => `
    <tr>
      <td>${d.label}</td>
      <td class="num">${d.n}</td>
      ${wrCell(d)}
      ${hidePnl ? '' : pnlCell(d)}
    </tr>`).join('');
  return `
    <div class="an-card">
      <h4>${title}</h4>
      ${note ? `<p class="an-note">${note}</p>` : ''}
      <table class="an-table">
        <thead><tr><th>${title.includes('Pair') ? 'Pair' : ''}</th><th class="num">n</th><th class="num">Win&nbsp;rate</th>${hidePnl ? '' : '<th class="num">P&amp;L</th>'}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
}

function sentimentCard(s) {
  if (!s) return '';
  const cov = s.coverage_pct;
  const warn = s.with_sentiment === 0
    ? `<p class="an-warn">⚠ Sentiment is not being captured (0 of ${s.resolved} resolved trades).
       PO only streams crowd-sentiment while dwelling on a symbol; the live scan
       monopolises the single WS session, so no frames arrive. Capture needs a
       dedicated approach — pending decision.</p>`
    : '';
  const rows = [];
  if (s.aligned) rows.push(s.aligned);
  if (s.contra) rows.push(s.contra);
  const buckets = (s.buckets || []);
  return `
    <div class="an-card">
      <h4>Sentiment</h4>
      <p class="an-note">Coverage: ${s.with_sentiment} / ${s.resolved} resolved (${cov}%)</p>
      ${warn}
      ${buckets.length ? table('By crowd buy% bucket', buckets) : ''}
      ${rows.length ? table('Crowd alignment', rows) : ''}
    </div>`;
}

function render(data) {
  if (!root) return;
  if (!data) { root.innerHTML = '<p class="an-empty">Loading…</p>'; return; }
  const be = (data.breakeven * 100).toFixed(2);
  root.innerHTML = `
    <div class="an-head">
      <div class="seg" id="an-seg" role="group" aria-label="Window">
        <button data-w="SINCE5AM" class="${currentWindow === 'SINCE5AM' ? 'on' : ''}">Since 5am (stable)</button>
        <button data-w="ALL" class="${currentWindow === 'ALL' ? 'on' : ''}">All history</button>
      </div>
      <span class="an-be">Break-even @92% payout = ${be}% · green = edge</span>
    </div>
    <div class="an-grid">
      ${table('Headline (real vs shadow)', data.headline)}
      ${table('By source / shadow kind', data.by_source)}
      ${table('By expiry (real)', data.by_expiry)}
      ${table('Shadow expiry experiment', data.shadow_expiry)}
      ${table('By direction (real)', data.by_direction)}
      ${table('By signal — win% when it agreed', data.by_signal, { hidePnl: true, note: 'Out of 11 signals; none individually predictive if all ≈ break-even.' })}
      ${table('By agreement count (real)', data.by_agreement)}
      ${table('By pair (real, n≥5)', data.by_pair)}
      ${sentimentCard(data.sentiment)}
    </div>`;

  const seg = root.querySelector('#an-seg');
  if (seg) {
    seg.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-w]');
      if (!btn) return;
      const w = btn.dataset.w;
      if (w === currentWindow) return;
      currentWindow = w;
      load(true);
    });
  }
}

async function load(force = false) {
  if (loaded && !force) return;
  try {
    render(null);
    const data = await api.analysis(currentWindow);
    loaded = true;
    render(data);
  } catch (e) {
    if (root) root.innerHTML = `<p class="an-empty">Analysis unavailable (${e.status || 'error'}).</p>`;
  }
}

export function initAnalysis(sel) {
  root = document.querySelector(sel);
  // Lazy-load when the Analysis tab is first shown.
  window.addEventListener('hashchange', () => {
    if (location.hash.replace('#', '') === 'analysis') load();
  });
  if (location.hash.replace('#', '') === 'analysis') load();
}
