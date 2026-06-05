// ws.js — reconnecting WebSocket client (§4.3).
// Exponential backoff with jitter, heartbeat ping, status callbacks, and
// typed message dispatch. Never throws into callers.

const MAX_BACKOFF = 15000;
const BASE_BACKOFF = 500;
const PING_INTERVAL = 20000;

export class ReconnectingWS {
  /**
   * @param {string} url            ws url (or path; resolved against location)
   * @param {object} handlers       { onStatus(status), onMessage(type, data) }
   */
  constructor(url, { onStatus = () => {}, onMessage = () => {} } = {}) {
    this.url = resolveWsUrl(url);
    this.onStatus = onStatus;
    this.onMessage = onMessage;
    this.ws = null;
    this.attempt = 0;
    this.closedByUser = false;
    this._pingTimer = null;
    this._reconnectTimer = null;
    this._everConnected = false;
  }

  connect() {
    this.closedByUser = false;
    this._open();
  }

  _open() {
    this._status(this._everConnected ? 'reconnecting' : 'connecting');
    let ws;
    try {
      ws = new WebSocket(this.url);
    } catch (e) {
      this._scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.addEventListener('open', () => {
      this.attempt = 0;
      this._everConnected = true;
      this._status('live');
      this._startPing();
    });

    ws.addEventListener('message', (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (!msg || typeof msg !== 'object') return;
      if (msg.type === 'pong') return;
      try { this.onMessage(msg.type, msg.data); } catch (e) { console.error('[ws] handler', e); }
    });

    ws.addEventListener('close', () => {
      this._stopPing();
      if (this.closedByUser) { this._status('closed'); return; }
      this._scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      // close will fire next; just ensure socket is torn down
      try { ws.close(); } catch (e) { /* ignore */ }
    });
  }

  _scheduleReconnect() {
    this._status('reconnecting');
    const backoff = Math.min(MAX_BACKOFF, BASE_BACKOFF * 2 ** this.attempt);
    const jitter = Math.random() * backoff * 0.3;
    this.attempt += 1;
    clearTimeout(this._reconnectTimer);
    this._reconnectTimer = setTimeout(() => this._open(), backoff + jitter);
  }

  _startPing() {
    this._stopPing();
    this._pingTimer = setInterval(() => this.send({ type: 'ping' }), PING_INTERVAL);
  }

  _stopPing() {
    if (this._pingTimer) { clearInterval(this._pingTimer); this._pingTimer = null; }
  }

  send(obj) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try { this.ws.send(JSON.stringify(obj)); } catch (e) { /* ignore */ }
    }
  }

  _status(s) {
    try { this.onStatus(s); } catch (e) { /* ignore */ }
  }

  close() {
    this.closedByUser = true;
    clearTimeout(this._reconnectTimer);
    this._stopPing();
    if (this.ws) { try { this.ws.close(); } catch (e) { /* ignore */ } }
  }
}

export function resolveWsUrl(url) {
  if (/^wss?:\/\//.test(url)) return url;
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const path = url.startsWith('/') ? url : `/${url}`;
  return `${proto}//${location.host}${path}`;
}

export default ReconnectingWS;
