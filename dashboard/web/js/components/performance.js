// components/performance.js — equity/P&L SVG curve + win/loss distribution.
// Range toggle (1H/1D/1W/ALL), break-even line, crosshair + value tooltip,
// smooth update when new points arrive. X axis is TIME, spanning the full
// selected window (trades plot at their actual timestamps, not evenly spaced).
import store from '../store.js';
import * as fmt from '../format.js';

const W = 980;
const H = 260;
const PAD = { l: 52, r: 18, t: 14, b: 30 };

// Selected-range duration in ms (ALL = derive from data)
const RANGE_MS = { '1H': 3600e3, '1D': 86400e3, '1W': 7 * 86400e3 };

function fmtTick(ms, range) {
  const d = new Date(ms);
  if (range === '1H' || range === '1D') {
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  if (range === '1W') {
    return d.toLocaleDateString([], { weekday: 'short' }) + ' ' +
           d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export function initPerformance({ chartSel, segSel, winlossSel, onRange } = {}) {
  const chartWrap = document.querySelector(chartSel);
  const seg = document.querySelector(segSel);
  const wl = document.querySelector(winlossSel);
  if (!chartWrap) return;

  let current = null; // last performance payload
  let points = [];     // [{t, cum_pnl}]
  let scale = null;     // {x(i), y(v), min, max}

  // range segment buttons
  if (seg) {
    seg.addEventListener('click', (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      seg.querySelectorAll('button').forEach((b) => b.classList.remove('on'));
      btn.classList.add('on');
      if (onRange) onRange(btn.textContent.trim());
    });
  }

  // tooltip (reuse the global .tooltip style)
  const tip = document.createElement('div');
  tip.className = 'tooltip';
  document.body.appendChild(tip);

  function render(perf) {
    current = perf;
    if (!perf) { chartWrap.innerHTML = '<div class="empty">Loading…</div>'; return; }
    points = Array.isArray(perf.equity) ? perf.equity : [];
    if (points.length < 2) {
      chartWrap.innerHTML = '<div class="empty">Not enough data for this range</div>';
      scale = null;
    } else {
      drawChart();
    }
    drawWinLoss(perf.winloss || {});
  }

  function drawChart() {
    const vals = points.map((p) => p.cum_pnl);
    const min = Math.min(...vals, 0);
    const max = Math.max(...vals, 0);
    const span = (max - min) || 1;

    // Time window: fixed ranges anchor to "now" and span backwards; ALL spans
    // from the first to the last trade. Trades plot at their real timestamps.
    const range = (current && current.range) || 'ALL';
    const times = points.map((p) => new Date(p.t).getTime());
    let t1, t0;
    if (RANGE_MS[range]) {
      t1 = Date.now();
      t0 = t1 - RANGE_MS[range];
    } else {
      t0 = Math.min(...times);
      t1 = Math.max(...times);
    }
    const tSpan = (t1 - t0) || 1;

    const x = (ms) => PAD.l + ((ms - t0) / tSpan) * (W - PAD.l - PAD.r);
    const y = (v) => PAD.t + (1 - (v - min) / span) * (H - PAD.t - PAD.b);
    scale = { x, y, min, max, times };

    const css = getComputedStyle(document.documentElement);
    const ACC = (css.getPropertyValue('--accent') || '#2dd4bf').trim();
    const GRID = (css.getPropertyValue('--stroke') || '#1e2733').trim();
    const ZERO = (css.getPropertyValue('--tx-2') || '#5f7283').trim();

    const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(times[i]).toFixed(1)},${y(p.cum_pnl).toFixed(1)}`).join(' ');
    const area = `${line} L${x(times[times.length - 1]).toFixed(1)},${y(min).toFixed(1)} L${x(times[0]).toFixed(1)},${y(min).toFixed(1)} Z`;
    const zeroY = y(0);

    // Horizontal $ gridlines (Y axis)
    let grid = '';
    for (let g = 0; g <= 4; g++) {
      const v = min + span * g / 4;
      const gy = y(v);
      grid += `<line x1="${PAD.l}" y1="${gy}" x2="${W - PAD.r}" y2="${gy}" stroke="${GRID}" stroke-width="1"/>`
        + `<text x="${PAD.l - 8}" y="${gy + 3}" fill="${ZERO}" font-size="9" text-anchor="end" font-family="monospace">$${v.toFixed(0)}</text>`;
    }

    // Vertical time gridlines + labels (X axis) spanning the selected window
    for (let g = 0; g <= 5; g++) {
      const tms = t0 + tSpan * g / 5;
      const gx = PAD.l + (g / 5) * (W - PAD.l - PAD.r);
      const anchor = g === 0 ? 'start' : g === 5 ? 'end' : 'middle';
      grid += `<line x1="${gx}" y1="${PAD.t}" x2="${gx}" y2="${H - PAD.b}" stroke="${GRID}" stroke-width="1" opacity="0.5"/>`
        + `<text x="${gx}" y="${H - PAD.b + 14}" fill="${ZERO}" font-size="9" text-anchor="${anchor}" font-family="monospace">${fmtTick(tms, range)}</text>`;
    }

    const lastI = points.length - 1;
    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Per-trade markers at actual trade times
    const dots = points.map((p, i) =>
      `<circle cx="${x(times[i]).toFixed(1)}" cy="${y(p.cum_pnl).toFixed(1)}" r="2" fill="${ACC}" opacity="0.55"/>`
    ).join('');

    chartWrap.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet" class="equity-svg">
      <defs>
        <linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${ACC}" stop-opacity="0.28"/>
          <stop offset="100%" stop-color="${ACC}" stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${grid}
      <line x1="${PAD.l}" y1="${zeroY}" x2="${W - PAD.r}" y2="${zeroY}" stroke="${ZERO}" stroke-width="1" stroke-dasharray="3 3"/>
      <path d="${area}" fill="url(#ag)"/>
      <path d="${line}" fill="none" stroke="${ACC}" stroke-width="2" stroke-linejoin="round" class="${reduce ? '' : 'equity-line'}"/>
      ${dots}
      <circle cx="${x(times[lastI])}" cy="${y(points[lastI].cum_pnl)}" r="7" fill="${ACC}" opacity="0.18"/>
      <circle cx="${x(times[lastI])}" cy="${y(points[lastI].cum_pnl)}" r="3.5" fill="${ACC}"/>
      <line data-cross x1="0" y1="${PAD.t}" x2="0" y2="${H - PAD.b}" stroke="${ACC}" stroke-width="1" stroke-dasharray="2 3" opacity="0" />
      <circle data-dot r="4" fill="${ACC}" stroke="#0a0e14" stroke-width="1.5" opacity="0" />
      <rect data-hit x="${PAD.l}" y="${PAD.t}" width="${W - PAD.l - PAD.r}" height="${H - PAD.t - PAD.b}" fill="transparent" />
    </svg>`;

    wireCrosshair(chartWrap.querySelector('svg'));
  }

  function wireCrosshair(svg) {
    if (!svg || !scale) return;
    const cross = svg.querySelector('[data-cross]');
    const dot = svg.querySelector('[data-dot]');
    const hit = svg.querySelector('[data-hit]');

    function locate(evt) {
      const rect = svg.getBoundingClientRect();
      const sx = (evt.clientX - rect.left) / rect.width * W; // to viewBox space
      // nearest point by x position (timestamps are not evenly spaced)
      let best = 0, bestDist = Infinity;
      for (let i = 0; i < points.length; i++) {
        const d = Math.abs(scale.x(scale.times[i]) - sx);
        if (d < bestDist) { bestDist = d; best = i; }
      }
      return best;
    }

    hit.addEventListener('mousemove', (evt) => {
      const i = locate(evt);
      const p = points[i];
      const px = scale.x(scale.times[i]);
      const py = scale.y(p.cum_pnl);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('opacity', '1');
      dot.setAttribute('cx', px); dot.setAttribute('cy', py); dot.setAttribute('opacity', '1');

      tip.innerHTML = `<div class="tt-grid" style="grid-template-columns:auto 1fr">
        <span>Time</span><b class="mono">${fmt.time(p.t)}</b>
        <span>Cum. P&amp;L</span><b class="mono ${fmt.pnlClass(p.cum_pnl)}">${fmt.pnl(p.cum_pnl)}</b>
      </div>`;
      tip.classList.add('show');
      let tx = evt.clientX + 16;
      if (tx + tip.offsetWidth > window.innerWidth - 8) tx = evt.clientX - tip.offsetWidth - 16;
      let ty = evt.clientY - tip.offsetHeight - 12;
      if (ty < 8) ty = evt.clientY + 16;
      tip.style.left = `${tx}px`;
      tip.style.top = `${ty}px`;
    });

    hit.addEventListener('mouseleave', () => {
      cross.setAttribute('opacity', '0');
      dot.setAttribute('opacity', '0');
      tip.classList.remove('show');
    });
  }

  function drawWinLoss(w) {
    if (!wl) return;
    const wins = w.wins || 0;
    const losses = w.losses || 0;
    const draws = w.draws || 0;
    const total = wins + losses + draws || 1;
    const pw = (wins / total) * 100;
    const pl = (losses / total) * 100;
    const pd = (draws / total) * 100;
    const wr = total ? Math.round((wins / total) * 100) : 0;
    wl.innerHTML = `
      <h4>Win / Loss Distribution</h4>
      <div class="wl-bar">
        <div class="w" style="width:${pw}%"></div>
        <div class="l" style="width:${pl}%"></div>
        <div class="d" style="width:${pd}%"></div>
      </div>
      <div class="wl-meta">
        <span class="up">${wins} Wins · ${wr}%</span>
        <span class="down">${losses} Losses · ${Math.round(pl)}%</span>
        <span class="muted">${draws} Draws</span>
      </div>`;
  }

  store.subscribe('performance', render);
}
