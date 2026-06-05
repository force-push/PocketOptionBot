// components/settings.js — Settings form bound to GET/POST /api/settings.
// - DEMO<->LIVE switch opens a confirm modal and posts confirm_live:true
// - masked secret fields only send when the user edits them
// - "restart required" banner when the response lists requires_restart
// - inline validation errors
import store from '../store.js';
import api from '../api.js';

const MASK = '••••';

export function initSettings({ rootSel, onChanged } = {}) {
  const root = document.querySelector(rootSel);
  if (!root) return;

  let groups = [];
  let dirty = {};          // key -> new value (only changed fields)
  let pendingMode = null;   // 'LIVE' awaiting confirm
  let errors = {};

  function render(payload) {
    if (!payload) { root.innerHTML = settingsSkeleton(); return; }
    groups = payload.groups || [];
    dirty = {};
    errors = {};
    root.innerHTML = template(groups);
    bind();
  }

  function template(grps) {
    return `
      <div class="warn-note" id="set-warn">
        <span>⚠️</span>
        <div><b>LIVE mode trades real money.</b> The demo guard in
          <code>broker/po_api.py</code> aborts any trade if the SSID is live while
          mode is DEMO. Keep DEMO as the default for testing.</div>
      </div>
      <div id="restart-banner" class="restart-banner" hidden>
        <span>↻</span>
        <div>
          <b>Bot restart required</b> — stop and re-run <code>python3 main_v2.py</code> to apply:
          <span id="restart-fields" style="color:var(--accent)"></span>
        </div>
      </div>
      <div id="save-status" class="save-status" hidden></div>
      <div class="settings-grid">
        ${grps.map(groupCard).join('')}
      </div>
      <div class="save-bar">
        <button class="btn ghost" data-action="reset">Reset</button>
        <button class="btn primary" data-action="save">Save Changes</button>
      </div>`;
  }

  function groupCard(g) {
    return `<div class="set-card${g.span2 ? ' span2' : ''}">
      <div class="h"><div class="ic">${g.icon || ''}</div>
        <div><h3>${g.title}</h3><p>${g.subtitle || ''}</p></div></div>
      <div class="set-body">
        ${g.fields.map((f) => fieldRow(f)).join('')}
      </div>
    </div>`;
  }

  function fieldRow(f) {
    const label = `<div class="k">${f.label}${f.hint || f.key.startsWith('_') === false
      ? ` <small>${f.hint ? f.hint + ' · ' : ''}${f.key.startsWith('_') ? '' : `<code>${f.key}</code>`}</small>` : ''}</div>`;
    return `<div class="field" data-field="${f.key}">
      ${label}
      ${control(f)}
      <div class="field-err" hidden></div>
    </div>`;
  }

  function control(f) {
    switch (f.type) {
      case 'mode':
        return `<div class="modeswitch" data-control="mode" data-key="${f.key}">
          <button data-mode="DEMO" class="${f.value === 'DEMO' ? 'demo-on' : ''}">DEMO</button>
          <button data-mode="LIVE" class="${f.value === 'LIVE' ? 'live-on' : ''}">LIVE</button>
        </div>`;
      case 'toggle':
        return `<label class="toggle"><input type="checkbox" data-key="${f.key}" ${f.value ? 'checked' : ''}><span class="sl"></span></label>`;
      case 'ratio': {
        const v = Math.round((f.value ?? 0) * 100);
        return `<div class="range"><input type="range" min="0" max="100" value="${v}" data-key="${f.key}" data-ratio="1"><b>${(v / 100).toFixed(2)}</b></div>`;
      }
      case 'number':
        return `<input type="number" value="${f.value}" step="${f.step || 'any'}" data-key="${f.key}">`;
      case 'secret':
        return `<input type="password" value="${MASK}" data-key="${f.key}" data-secret="1" autocomplete="off">`;
      case 'pill':
        return `<span class="pill ${f.variant || 'draw'}">${f.value}</span>`;
      case 'text':
      default:
        return `<input type="text" value="${escapeAttr(f.value)}" data-key="${f.key}">`;
    }
  }

  function bind() {
    // text/number/checkbox/range inputs
    root.querySelectorAll('input[data-key]').forEach((inp) => {
      inp.addEventListener('input', () => {
        const key = inp.dataset.key;
        clearError(key);
        if (inp.dataset.secret) {
          // only treat as changed once the user replaces the mask
          if (inp.value === MASK || inp.value === '') { delete dirty[key]; return; }
          dirty[key] = inp.value;
        } else if (inp.type === 'checkbox') {
          dirty[key] = inp.checked;
        } else if (inp.dataset.ratio) {
          const ratio = Number(inp.value) / 100;
          dirty[key] = ratio;
          const b = inp.parentElement.querySelector('b');
          if (b) b.textContent = ratio.toFixed(2);
        } else if (inp.type === 'number') {
          dirty[key] = inp.value === '' ? '' : Number(inp.value);
        } else {
          dirty[key] = inp.value;
        }
      });
      // clear secret mask on focus so edits are obvious
      if (inp.dataset.secret) {
        inp.addEventListener('focus', () => { if (inp.value === MASK) inp.value = ''; });
        inp.addEventListener('blur', () => { if (inp.value === '') inp.value = MASK; });
      }
    });

    // mode switch
    const ms = root.querySelector('[data-control="mode"]');
    if (ms) {
      ms.querySelectorAll('button').forEach((btn) => {
        btn.addEventListener('click', () => {
          const mode = btn.dataset.mode;
          const key = ms.dataset.key;
          if (mode === 'LIVE') {
            openLiveModal(() => applyMode(ms, key, 'LIVE'));
          } else {
            pendingMode = null;
            applyMode(ms, key, 'DEMO');
          }
        });
      });
    }

    root.querySelector('[data-action="reset"]')?.addEventListener('click', () => {
      pendingMode = null;
      render(store.get('settings'));
    });
    root.querySelector('[data-action="save"]')?.addEventListener('click', save);
  }

  function applyMode(ms, key, mode) {
    ms.querySelectorAll('button').forEach((b) => b.classList.remove('demo-on', 'live-on'));
    ms.querySelector(`[data-mode="${mode}"]`).classList.add(mode === 'DEMO' ? 'demo-on' : 'live-on');
    dirty[key] = mode;
    pendingMode = mode === 'LIVE' ? 'LIVE' : null;
    root.querySelector('#set-warn')?.classList.toggle('hot', mode === 'LIVE');
  }

  async function save() {
    if (Object.keys(dirty).length === 0) {
      flashStatus('No changes to save.', 'info');
      return;
    }
    const confirmLive = pendingMode === 'LIVE';
    setSaving(true);
    try {
      const resp = store.get('demo')
        ? simulateSave(dirty, confirmLive)
        : await api.saveSettings(dirty, confirmLive);
      handleResponse(resp);
    } catch (e) {
      const body = e.body;
      if (body && body.errors) { showErrors(body.errors); flashStatus('Fix the highlighted fields.', 'error'); }
      else flashStatus(`Save failed (${e.status || 'network'}).`, 'error');
    } finally {
      setSaving(false);
    }
  }

  function handleResponse(resp) {
    if (!resp) return;
    if (resp.errors && Object.keys(resp.errors).length) {
      showErrors(resp.errors);
      flashStatus('Fix the highlighted fields.', 'error');
      return;
    }
    flashStatus('Settings saved.', 'ok');
    if (resp.requires_restart && resp.requires_restart.length) {
      const banner = root.querySelector('#restart-banner');
      const fields = root.querySelector('#restart-fields');
      if (fields) fields.textContent = resp.requires_restart.join(', ');
      if (banner) banner.hidden = false;
    }
    // merge applied values back into the store payload so a re-render reflects them
    const payload = store.get('settings');
    if (payload && resp.applied) {
      for (const g of payload.groups) {
        for (const f of g.fields) {
          if (f.key in resp.applied) {
            f.value = f.type === 'secret' ? MASK : resp.applied[f.key];
          }
        }
      }
      store.setSettings(payload); // triggers re-render
    }
    dirty = {};
    pendingMode = null;
    if (onChanged) onChanged(resp);
  }

  function showErrors(errs) {
    errors = errs;
    for (const [key, msg] of Object.entries(errs)) {
      const field = root.querySelector(`.field[data-field="${cssEscape(key)}"]`);
      if (!field) continue;
      const errEl = field.querySelector('.field-err');
      field.classList.add('has-error');
      if (errEl) { errEl.textContent = msg; errEl.hidden = false; }
    }
  }

  function clearError(key) {
    const field = root.querySelector(`.field[data-field="${cssEscape(key)}"]`);
    if (!field) return;
    field.classList.remove('has-error');
    const errEl = field.querySelector('.field-err');
    if (errEl) errEl.hidden = true;
  }

  function setSaving(on) {
    const btn = root.querySelector('[data-action="save"]');
    if (btn) { btn.disabled = on; btn.textContent = on ? 'Saving…' : 'Save Changes'; }
  }

  function flashStatus(msg, kind) {
    const el = root.querySelector('#save-status');
    if (!el) return;
    el.textContent = msg;
    el.className = `save-status ${kind}`;
    el.hidden = false;
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.hidden = true; }, 4000);
  }

  store.subscribe('settings', render);
}

/* ---------- LIVE confirmation modal ---------- */

function openLiveModal(onConfirm) {
  const existing = document.getElementById('live-modal');
  if (existing) existing.remove();
  const wrap = document.createElement('div');
  wrap.id = 'live-modal';
  wrap.className = 'modal-backdrop';
  wrap.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="lm-title">
      <div class="modal-h"><span class="modal-ic">⚠️</span><h3 id="lm-title">Switch to LIVE trading?</h3></div>
      <p class="modal-body">This will place trades with <b>real money</b>. The server
        re-validates your SSID; if it is not a live session the switch is rejected
        (fail-closed). Make sure your risk limits are configured.</p>
      <label class="modal-confirm"><input type="checkbox" id="lm-ack"> I understand this trades real funds.</label>
      <div class="modal-actions">
        <button class="btn ghost" data-m="cancel">Cancel</button>
        <button class="btn danger" data-m="confirm" disabled>Enable LIVE</button>
      </div>
    </div>`;
  document.body.appendChild(wrap);

  const ack = wrap.querySelector('#lm-ack');
  const confirmBtn = wrap.querySelector('[data-m="confirm"]');
  ack.addEventListener('change', () => { confirmBtn.disabled = !ack.checked; });

  function close() { wrap.remove(); document.removeEventListener('keydown', onKey); }
  function onKey(e) { if (e.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);

  wrap.addEventListener('click', (e) => { if (e.target === wrap) close(); });
  wrap.querySelector('[data-m="cancel"]').addEventListener('click', close);
  confirmBtn.addEventListener('click', () => { onConfirm(); close(); });
  setTimeout(() => ack.focus(), 0);
}

/* ---------- demo-mode local save simulation ---------- */

function simulateSave(fields, confirmLive) {
  // LIVE guard: refuse the flip unless confirmed (mirrors backend behaviour)
  if (fields.TRADE_MODE === 'LIVE' && !confirmLive) {
    return { ok: false, applied: {}, errors: { TRADE_MODE: 'confirm_live required to enable LIVE' }, requires_restart: [] };
  }
  const restartKeys = ['TRADE_MODE', 'TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'SIGNAL_BOT_USERNAME', 'PO_SSID'];
  const requires_restart = Object.keys(fields).filter((k) => restartKeys.includes(k));
  return { ok: true, applied: { ...fields }, errors: {}, requires_restart };
}

/* ---------- helpers ---------- */

function settingsSkeleton() {
  return `<div class="settings-grid">${Array.from({ length: 4 }, () => `
    <div class="set-card"><div class="h"><div class="ic sk"></div><div><div class="sk sk-line" style="width:120px;height:13px"></div></div></div>
      <div class="set-body">${Array.from({ length: 3 }, () => '<div class="field"><div class="sk sk-line" style="width:60%;height:12px"></div><div class="sk sk-line" style="width:80px;height:28px"></div></div>').join('')}</div></div>`).join('')}</div>`;
}

function escapeAttr(s) {
  return String(s ?? '').replace(/"/g, '&quot;');
}
function cssEscape(s) {
  if (window.CSS && CSS.escape) return CSS.escape(s);
  return String(s).replace(/["\\]/g, '\\$&');
}
