// components/history.js — Trade History table + click-to-open detail modal.
import store from '../store.js';
import * as fmt from '../format.js';

// ── Modal singleton ──────────────────────────────────────────────────────────

const overlay  = document.getElementById('trade-modal');
const modalEl  = overlay?.querySelector('.modal-card');
const contentEl = document.getElementById('modal-content');
const closeBtn  = document.getElementById('modal-close');

function openModal(cycleId, fallbackRow) {
  if (!overlay || !contentEl) {
    console.warn('[modal] #trade-modal not found — did the page load before the new index.html? Hard-refresh the browser.');
    return;
  }
  contentEl.innerHTML = '<div style="color:var(--tx-2);padding:24px 0;text-align:center">Loading…</div>';
  overlay.hidden = false;
  document.body.style.overflow = 'hidden';

  if (store.get('demo') || !cycleId) {
    // Demo mode — load the sample detail so the modal shows a full breakdown
    const sampleUrl = new URL('../sample/trade_detail.json', import.meta.url);
    fetch(sampleUrl)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(d => {
        // Overlay the actual row fields so pair/result/time are accurate
        contentEl.innerHTML = detailHtml({ ...d, ...fallbackRow });
      })
      .catch(() => { contentEl.innerHTML = detailHtml(fallbackRow || {}); });
    return;
  }

  fetch(`/api/trade/${encodeURIComponent(cycleId)}`)
    .then(r => r.ok ? r.json() : Promise.reject(r.status))
    .then(d => { contentEl.innerHTML = detailHtml(d); })
    .catch(err => {
      // Fall back to whatever row data we already have
      contentEl.innerHTML = detailHtml(fallbackRow || {});
      console.warn('[modal] full detail fetch failed:', err);
    });
}

function closeModal() {
  if (!overlay) return;
  overlay.hidden = true;
  document.body.style.overflow = '';
}

if (closeBtn)  closeBtn.addEventListener('click', closeModal);
if (overlay)   overlay.addEventListener('click', e => { if (e.target === overlay) closeModal(); });
document.addEventListener('keydown', e => { if (e.key === 'Escape' && overlay && !overlay.hidden) closeModal(); });

// ── History table ────────────────────────────────────────────────────────────

export function initHistory(rootSel, countSel) {
  const tbody  = typeof rootSel === 'string' ? document.querySelector(rootSel) : rootSel;
  const countEl = countSel ? document.querySelector(countSel) : null;
  if (!tbody) return;

  let rows = [];

  function render(list) {
    rows = Array.isArray(list) ? list : [];
    if (countEl) {
      const resolved = rows.filter(r => r.decision !== 'SKIP').length;
      countEl.textContent = `resolved · ${resolved}`;
    }
    if (!rows.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="3"><div class="empty">No trades yet</div></td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((h, i) => rowHtml(h, i)).join('');

    const fresh = rows.filter(r => r._new);
    if (fresh.length) setTimeout(() => { fresh.forEach(r => { delete r._new; }); }, 1600);
  }

  function rowHtml(h, i) {
    const isSkip = h.decision === 'SKIP';
    const parts  = fmt.pairParts(h.pair_raw);
    const dirCls = (h.dir || '').toLowerCase();
    const newCls = h._new  ? ' row-new'  : '';
    const skipCls = isSkip ? ' row-skip' : '';
    // Shadow = a deliberate data-collection trade the strategy would normally skip.
    // Mark it visually so real strategy trades aren't read together with test trades.
    const shadowCls = h.shadow ? ' row-shadow' : '';
    const shadowTag = h.shadow
      ? `<span class="shadow-tag" title="Shadow trade — intentional data-collection trade (would skip: ${h.would_skip_reason || '?'}). Not a real strategy trade.">TEST</span>`
      : '';

    const result = h.outcome || h.result;  // outcome from resolved event, fallback to result
    const resultCell = isSkip
      ? `<span class="res-sym draw" title="skipped">–</span><span class="muted" style="margin-left:7px">SKIP</span>`
      : `<span class="res-sym ${result || 'draw'}">${fmt.resSym(result)}</span>` +
        `<span class="${fmt.pnlClass(h.pnl)}" style="margin-left:7px">${fmt.pnl(h.pnl)}</span>`;

    return `<tr data-i="${i}" class="hist-row${newCls}${skipCls}${shadowCls}" tabindex="0" role="button" aria-label="View trade detail">
      <td class="mono muted">${fmt.time(h.ts)}</td>
      <td>
        <span class="dir-arrow ${dirCls}" title="${h.dir || ''}">${fmt.dirSym(h.dir)}</span>
        <span class="pair">${parts.base}${parts.otc ? '<span class="otc">otc</span>' : ''}</span>${shadowTag}
      </td>
      <td class="num">${resultCell}</td>
    </tr>`;
  }

  tbody.addEventListener('click', e => {
    const tr = e.target.closest('tr.hist-row');
    if (!tr) return;
    const h = rows[+tr.dataset.i];
    if (h) openModal(h.cycle_id, h);
  });

  tbody.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const tr = e.target.closest('tr.hist-row');
    if (!tr) return;
    e.preventDefault();
    const h = rows[+tr.dataset.i];
    if (h) openModal(h.cycle_id, h);
  });

  store.subscribe('history', render);
}

// ── Detail HTML builder ──────────────────────────────────────────────────────

function detailHtml(d) {
  const isSkip   = d.decision === 'SKIP';
  const result   = d.outcome || d.result;  // outcome from resolved event, fallback to result
  const isWin    = result === 'win';
  const isLoss   = result === 'loss';
  const parts    = fmt.pairParts(d.pair_raw);
  const pairLabel = `${parts.base}${parts.otc ? ' <span class="otc" style="font-size:11px">OTC</span>' : ''}`;
  const dir      = d.bot_direction || d.dir || '';
  const dirCls   = dir.toLowerCase();
  const resCls   = isWin ? 'up' : isLoss ? 'down' : 'muted';
  const resLabel = isSkip ? 'SKIP' : (result || 'PENDING').toUpperCase();

  // ── Header ────────────────────────────────────────────────────────────────
  const header = `
    <div class="md-header">
      <span class="md-pair">${pairLabel}</span>
      ${dir ? `<span class="pill ${dirCls}">${fmt.dirSym(dir)} ${dir}</span>` : ''}
      <span class="pill ${resCls}" style="border-color:transparent;background:var(--${isWin?'up-dim':isLoss?'down-dim':'bg-3'})">
        ${isWin ? '▲' : isLoss ? '▼' : '○'} ${resLabel}
        ${!isSkip && d.pnl != null ? `&nbsp;${fmt.pnl(d.pnl)}` : ''}
      </span>
      ${d.shadow ? `<span class="shadow-tag" title="Intentional data-collection trade">TEST</span>` : ''}
      <span class="md-time">${fmt.time(d.ts)}</span>
    </div>
    ${d.shadow ? `<div class="md-shadow-note">🧪 <b>Shadow trade</b> — intentionally placed for data collection (would normally skip: <b>${escHtml(d.would_skip_reason || '?')}</b>). Excluded from the real strategy's win-rate and risk stats.</div>` : ''}`;

  // ── Bot section ───────────────────────────────────────────────────────────
  const botSection = `
    <div class="md-section">
      <div class="md-section-title">PO Broker Bot</div>
      <div class="md-bot-row" style="display:flex;gap:16px;align-items:center;font-size:13px">
        <div><span style="color:var(--tx-2)">Direction</span> <b class="pill ${dirCls}" style="font-size:10px;padding:2px 8px;margin-left:4px">${fmt.dirSym(dir)} ${dir || '—'}</b></div>
        <div><span style="color:var(--tx-2)">Win rate</span> <b class="${(d.bot_win_rate||0) >= 0.8 ? 'up' : 'warn'}" style="margin-left:4px">${fmt.pct(d.bot_win_rate, 1)}</b></div>
        <div><span style="color:var(--tx-2)">Setup</span> <b style="margin-left:4px">${escHtml(d.bot_setup || '—')}</b></div>
        <div><span style="color:var(--tx-2)">Top pick</span> <b style="margin-left:4px">${d.bot_is_top_pick ? '<span class="up">✓</span>' : '<span class="muted">–</span>'}</b></div>
      </div>
      ${d.bot_indicators_raw ? `<div class="md-indicators">${escHtml(d.bot_indicators_raw)}</div>` : ''}
    </div>`;

  // ── Signal table ──────────────────────────────────────────────────────────
  const breakdown = d.our_signal_breakdown || {};
  const sigRows = Object.entries(breakdown).map(([name, vals]) => {
    const [sigDir, sigConf, sigReason] = Array.isArray(vals) ? vals : [null, 0, ''];
    const dc  = (sigDir || '').toLowerCase();
    const pct = Math.round((sigConf || 0) * 100);
    const dirLabel = sigDir
      ? `<span class="pill ${dc}" style="font-size:10px;padding:1px 6px">${sigDir}</span>`
      : `<span class="muted" style="font-size:11px">—</span>`;
    return `<tr>
      <td style="font-weight:500;padding-right:12px">${escHtml(name)}</td>
      <td>${dirLabel}</td>
      <td>
        <div class="sig-conf-bar">
          <div class="sig-bar-bg"><div class="sig-bar-fill ${dc || 'none'}" style="width:${pct}%"></div></div>
          <span class="sig-conf-val">${(sigConf||0).toFixed(3)}</span>
        </div>
      </td>
      <td class="sig-reason">${escHtml(sigReason || '')}</td>
    </tr>`;
  }).join('');

  const sigTable = `
    <div class="md-section">
      <div class="md-section-title">Internal TA Analysis</div>
      ${sigRows ? `
        <table class="sig-table">
          <thead><tr><th>Signal</th><th>Direction</th><th>Confidence</th><th>Reason</th></tr></thead>
          <tbody>${sigRows}</tbody>
        </table>` : '<div class="muted" style="font-size:12px">No signal data</div>'}
    </div>`;

  // ── Confluence ────────────────────────────────────────────────────────────
  const conf     = d.our_confluence_score;
  const ourDir   = d.our_direction;
  const totalSig = Object.keys(breakdown).length;

  const settings = store.get('settings') || {};
  const minAgreement = settings.min_signal_agreement ?? 2;
  let displayDir = ourDir;
  if (!displayDir) {
    // Count signals per direction to find the winner
    const callCount = Object.values(breakdown).filter(v => Array.isArray(v) && v[0] === 'CALL').length;
    const putCount  = Object.values(breakdown).filter(v => Array.isArray(v) && v[0] === 'PUT').length;
    displayDir = callCount >= putCount ? 'CALL' : putCount > 0 ? 'PUT' : null;
  }

  const agreed   = displayDir ? Object.values(breakdown).filter(v => Array.isArray(v) && v[0] === displayDir).length : 0;
  const confCls  = ourDir === 'CALL' ? 'up' : ourDir === 'PUT' ? 'down' : 'muted';
  const gatePass = ourDir != null && agreed >= minAgreement;

  const confSection = `
    <div class="md-section">
      <div class="md-section-title">Confluence Gate</div>
      <div class="md-conf-row">
        <span class="md-conf-score ${confCls}">${conf != null ? conf.toFixed(3) : '—'}</span>
        <div class="md-conf-meta">
          <div>${displayDir ? `<b>${displayDir}</b>` : '<span class="muted">No direction</span>'} &nbsp;·&nbsp; ${agreed}/${totalSig} signals agree</div>
          <div class="${gatePass ? 'gate-pass' : 'gate-fail'}">${ourDir ? (agreed >= minAgreement ? '✓ Gate passed (≥' + minAgreement + ' agree)' : `✗ Gate failed: only ${agreed} signal(s) on ${ourDir} (need ≥${minAgreement})`) : '✗ Gate failed (tie or no signals)'}</div>
        </div>
        ${d.combined_probability != null ? `<div class="mono" style="font-size:12px;color:var(--tx-1)">confidence&nbsp;<b>${(d.combined_probability*100).toFixed(1)}%</b>${d.calibrated_probability != null ? ` &nbsp;·&nbsp; <span style="color:var(--ac-1)">P(win)&nbsp;<b>${(d.calibrated_probability*100).toFixed(1)}%</b></span>` : ''}</div>` : ''}
      </div>
      <div class="md-agree-row">
        ${d.agreement
          ? `<span class="agree-yes">✓ Agreement</span><span style="color:var(--tx-1);font-size:12px">Bot and TA both say <b>${dir}</b></span>`
          : `<span class="agree-no">✗ Disagreement</span><span style="color:var(--tx-1);font-size:12px">Bot: <b>${dir}</b> &nbsp; TA: <b>${ourDir || 'None'}</b></span>`}
      </div>
    </div>`;

  // ── Trade info ────────────────────────────────────────────────────────────
  let tradeSection = '';
  if (!isSkip) {
    const pnlCls = d.pnl > 0 ? 'up' : d.pnl < 0 ? 'down' : 'muted';
    tradeSection = `
      <div class="md-section">
        <div class="md-section-title">Trade</div>
        ${d.trade_id ? `<div style="font-size:11px;color:var(--tx-2);padding:6px 0;font-family:var(--mono);word-break:break-all">ID: <b style="color:var(--tx-1)">${escHtml(d.trade_id)}</b></div>` : ''}
        <div class="md-trade-grid">
          <div class="md-stat">
            <div class="md-stat-label">Stake</div>
            <div class="md-stat-val">${fmt.money(d.stake)}</div>
          </div>
          <div class="md-stat">
            <div class="md-stat-label">Expiry</div>
            <div class="md-stat-val">${fmt.duration(d.expiry_seconds)}</div>
          </div>
          <div class="md-stat">
            <div class="md-stat-label">Payout</div>
            <div class="md-stat-val ${d.payout_pct != null ? (d.payout_pct >= 92 ? 'up' : d.payout_pct >= 85 ? 'warn' : 'down') : 'muted'}">${d.payout_pct != null ? d.payout_pct + '%' : '—'}</div>
          </div>
          <div class="md-stat">
            <div class="md-stat-label">P&amp;L</div>
            <div class="md-stat-val ${pnlCls}">${fmt.pnl(d.pnl)}</div>
          </div>
          <div class="md-stat">
            <div class="md-stat-label">Result</div>
            <div class="md-stat-val ${resCls}">${resLabel}</div>
          </div>
        </div>
        ${d.balance_before != null ? `
          <div class="md-agree-row" style="margin-top:8px;font-family:var(--mono);font-size:12px">
            <span style="color:var(--tx-2)">Balance</span>
            <span>${fmt.money(d.balance_before)}</span>
            <span style="color:var(--tx-2)">→</span>
            <span class="${pnlCls}">${d.balance_after != null ? fmt.money(d.balance_after) : '—'}</span>
          </div>` : ''}
      </div>`;
  } else {
    tradeSection = `
      <div class="md-section">
        <div class="md-section-title">Skip Reason</div>
        <div class="md-agree-row">
          <span class="agree-no">✗ ${escHtml(d.skip_reason || 'skipped')}</span>
        </div>
      </div>`;
  }

  return header + botSection + sigTable + confSection + tradeSection;
}

function escHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
}
