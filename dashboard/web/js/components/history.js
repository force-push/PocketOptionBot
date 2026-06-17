// components/history.js — Trade History table + click-to-open detail modal.
import store from '../store.js';
import * as fmt from '../format.js';

// ── Modal singleton ──────────────────────────────────────────────────────────

const overlay  = document.getElementById('trade-modal');
const modalEl  = overlay?.querySelector('.modal-card');
const contentEl = document.getElementById('modal-content');
const closeBtn  = document.getElementById('modal-close');

function openModal(lookupKey, fallbackRow) {
  if (!overlay || !contentEl) {
    console.warn('[modal] #trade-modal not found — did the page load before the new index.html? Hard-refresh the browser.');
    return;
  }
  contentEl.innerHTML = '<div style="color:var(--tx-2);padding:24px 0;text-align:center">Loading…</div>';
  overlay.hidden = false;
  document.body.style.overflow = 'hidden';

  if (store.get('demo') || !lookupKey) {
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

  fetch(`/api/trade/${encodeURIComponent(lookupKey)}`)
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
    const traded = rows.filter(r => r.decision !== 'SKIP');
    if (countEl) {
      countEl.textContent = `resolved · ${traded.length}`;
    }
    if (!traded.length) {
      tbody.innerHTML = `<tr class="empty-row"><td colspan="3"><div class="empty">No trades yet</div></td></tr>`;
      return;
    }
    tbody.innerHTML = traded.map((h, i) => rowHtml(h, i)).join('');

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
    // Use trade_id (unique per trade) as lookup key; fall back to cycle_id for SKIPs
    if (h) openModal(h.trade_id || h.cycle_id, h);
  });

  tbody.addEventListener('keydown', e => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    const tr = e.target.closest('tr.hist-row');
    if (!tr) return;
    e.preventDefault();
    const h = rows[+tr.dataset.i];
    if (h) openModal(h.trade_id || h.cycle_id, h);
  });

  store.subscribe('history', render);
}

// ── Skip reason formatter ────────────────────────────────────────────────────
// Converts raw diagnostic reason strings into a short human-readable label.
// The full metrics are already in the Flip Strategy Signals table below.

function formatSkipReason(reason) {
  if (!reason) return null;
  // Strip the trailing parenthetical diagnostic block "(ST=CALL adx=... etc)"
  const short = reason.replace(/\s*\(ST=.*\)\s*$/, '').trim();
  const r = short.toLowerCase();

  if (r.startsWith('bb_width') && r.includes('chop')) {
    const m = short.match(/([\d.]+)<([\d.]+)/);
    return m
      ? `Low volatility — bb_width ${m[1]} bps (min ${m[2]} bps)`
      : 'Low volatility (chop)';
  }
  if (r.startsWith('bb_width') && r.includes('whipsaw')) {
    const m = short.match(/([\d.]+)>([\d.]+)/);
    return m
      ? `High volatility — bb_width ${m[1]} bps (max ${m[2]} bps)`
      : 'High volatility (whipsaw)';
  }
  if (r.startsWith('weak macd gap')) {
    const m = short.match(/([\d.]+)<([\d.]+)/);
    return m
      ? `Weak MACD momentum — gap/ATR ${m[1]} (min ${m[2]})`
      : 'Weak MACD momentum';
  }
  if (r.startsWith('macd disagrees'))   return 'MACD direction disagrees with SuperTrend';
  if (r.startsWith('di disagrees'))     return 'DI direction disagrees with SuperTrend';
  if (r.startsWith('flip in adx dead')) {
    const m = short.match(/\[([\d.]+),([\d.]+)\)/);
    return m ? `ADX in dead zone [${m[1]}–${m[2]}]` : 'ADX dead zone';
  }
  if (r.startsWith('flip but adx')) {
    const m = short.match(/ADX<([\d.]+)/i);
    return m ? `ADX too low for flip (min ${m[1]})` : 'ADX too low';
  }
  if (r.startsWith('cont')) {
    return `Continuation gate: ${short.replace(/^cont[^ ]* /i, '')}`;
  }
  // Fallback: already-stripped short string
  return short;
}

// ── Detail HTML builder ──────────────────────────────────────────────────────

function detailHtml(d) {
  const isSkip   = d.decision === 'SKIP';
  const result   = d.outcome || d.result;  // outcome from resolved event, fallback to result
  const isWin    = result === 'win';
  const isLoss   = result === 'loss';
  const parts    = fmt.pairParts(d.pair_raw);
  const pairLabel = `${parts.base}${parts.otc ? ' <span class="otc" style="font-size:11px">OTC</span>' : ''}`;
  const dir      = d.dir || (d.flip_metrics && d.flip_metrics.st_dir) || '';
  const dirCls   = dir.toLowerCase();
  const resCls   = isWin ? 'up' : isLoss ? 'down' : 'muted';
  const resLabel = isSkip ? 'SKIP' : (result || 'PENDING').toUpperCase();

  // ── Header ────────────────────────────────────────────────────────────────
  const skipReason = d.would_skip_reason || (isSkip ? d.skip_reason : null);
  const skipLabel  = formatSkipReason(skipReason);
  const isShadow   = d.shadow && d.shadow_kind === 'flip_skip';
  const header = `
    <div class="md-header">
      <div class="md-pair-col">
        <span class="md-pair">${pairLabel}</span>
        ${skipLabel ? `<span class="md-skip-badge${isShadow ? ' md-skip-shadow' : ''}" title="${escHtml(skipReason)}">⊘ ${escHtml(skipLabel)}</span>` : ''}
      </div>
      ${dir ? `<span class="pill ${dirCls}">${fmt.dirSym(dir)} ${dir}</span>` : ''}
      <span class="pill ${resCls}" style="border-color:transparent;background:var(--${isWin?'up-dim':isLoss?'down-dim':'bg-3'})">
        ${isWin ? '▲' : isLoss ? '▼' : '○'} ${resLabel}
        ${!isSkip && d.pnl != null ? `&nbsp;${fmt.pnl(d.pnl)}` : ''}
      </span>
      <span class="md-time">${fmt.time(d.ts)}</span>
    </div>`;

  // ── Flip-strategy signals (the actual entry decision: SuperTrend flip /
  //    continuation, confirmed by MACD + ADX/DI + RSI, gated on dist & gap) ────
  const fm = d.flip_metrics;
  const flipSection = `
    <div class="md-section">
      <div class="md-section-title">Flip Strategy Signals</div>
      ${fm ? `
      <table class="sig-table">
        <thead><tr><th>Signal</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td style="font-weight:500">SuperTrend</td><td>
            <span class="pill ${(fm.st_dir||'').toLowerCase()}" style="font-size:10px;padding:1px 6px">${fm.st_dir||'—'}</span>
            ${fm.entry_kind ? `&nbsp;<span class="muted" style="font-size:11px">${escHtml(fm.entry_kind)}${fm.flipped ? ' · fresh flip' : ''}</span>` : ''}
          </td></tr>
          <tr><td style="font-weight:500">ADX (14)</td><td>${fm.adx ?? '—'} <span class="${fm.adx_rising ? 'up' : 'down'}">${fm.adx_rising ? '↑ rising' : '↓ falling'}</span></td></tr>
          <tr><td style="font-weight:500">+DI / −DI</td><td><span class="up">${fm.plus_di ?? '—'}</span> / <span class="down">${fm.minus_di ?? '—'}</span></td></tr>
          <tr><td style="font-weight:500">Dist from band</td><td>${fm.dist_atr ?? '—'} ATR</td></tr>
          <tr><td style="font-weight:500">RSI (14)</td><td>${fm.rsi ?? '—'}</td></tr>
          <tr><td style="font-weight:500">Bars since flip</td><td>${fm.bars_in_trend ?? '—'}</td></tr>
          <tr><td style="font-weight:500">MACD gap (12/26/9)</td><td>${fm.macd_gap != null ? Number(fm.macd_gap).toFixed(6) : '—'}</td></tr>
          <tr><td style="font-weight:500">MACD gap / ATR</td><td>${fm.macd_gap_atr ?? '—'}${fm.gap_at_flip != null ? ` <span class="muted">(at flip: ${fm.gap_at_flip})</span>` : ''}</td></tr>
          <tr><td style="font-weight:500">Gap expansion since flip</td><td>${fm.gap_expansion != null ? `<span class="${fm.gap_expansion >= 0 ? 'up' : 'down'}">${fm.gap_expansion >= 0 ? '+' : ''}${fm.gap_expansion}</span>` : '—'}</td></tr>
          <tr><td style="font-weight:500">MACD width consistency</td><td>${fm.macd_gap_std != null ? `std ${fm.macd_gap_std} · mean ${fm.macd_gap_mean ?? '—'}` : '—'}${fm.macd_sign_consistency != null ? ` <span class="muted">· same-side ${Math.round(fm.macd_sign_consistency * 100)}%</span>` : ''}</td></tr>
        </tbody>
      </table>` : '<div class="muted" style="font-size:12px">No signal data</div>'}
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

  return header + flipSection + tradeSection;
}

function escHtml(s) {
  return String(s ?? '').replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
}
