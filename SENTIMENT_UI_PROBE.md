# Sentiment UI Probe — PARKED 2026-06-13 (resume next session)

Goal: rediscover the WebSocket trigger that turns on PocketOption's
**traders'-choice / sentiment** stream, by matching live socket frames to the
UI. The in-bot collector captures **0** sentiment frames because that stream is
no longer emitted on a plain `changeSymbol` subscription (see
`memory/debug_sentiment_out_of_band.md` for the full proof).

## State at park

- In-bot collector + dashboard scaffolding: left in place, dormant
  (`DecisionRow.sentiment` is always `None`). User chose "leave as-is".
- Bot running normally in the supervisor.
- Diagnostic tools kept: `tools/po_probe.py`, `tools/po_sentiment_probe.py`,
  `tools/po_raw_shapes.py`.

## What we proved

- Standalone probe (bot stopped, clean dedicated subscription, 60s/asset): the
  only `[[...]]` frames are **3-element tick frames** `[["SYM", ts, price]]`.
  **Zero** 2-element `[["SYM",int]]` sentiment frames.
- The single-int sentiment frames were seen **only** in the original
  `po_probe.py` discovery run — which sent an extra nudge `42["favorite/get"]`
  right after `changeSymbol`. **Leading hypothesis:** the sentiment stream needs
  a trigger beyond `changeSymbol` (possibly `favorite/get` or a distinct
  subscribe event). The browser capture will confirm or replace this.

## Why the controlled-browser approach was abandoned (for now)

- `chrome-devtools-mcp` is **unstable in this environment** — the MCP server
  repeatedly loses its handle to the browser it launched, then every call hits
  the profile lock ("browser is already running … use --isolated"). The Google
  OAuth popup made it worse (untracked target).
- Google **blocks OAuth login** in the automation-flagged browser ("This browser
  or app may not be secure"). Native email/password login works, but only if the
  account has a PO password set.

## RESUME PLAN (do this next session)

Capture in the user's **own** Chrome (already logged into PocketOption) — no MCP,
no login fight. Open trading terminal on an asset showing the Traders' sentiment
bar, open DevTools → Console, paste the hook:

```js
(() => {
  window.__sent = window.__sent || [];
  window.__sentiment = window.__sentiment || [];
  if (!WebSocket.prototype.__hooked) {
    const _s = WebSocket.prototype.send;
    WebSocket.prototype.send = function(d){
      try { if (typeof d === 'string') { window.__sent.push(d);
        if(/changeSymbol|subscrib|sentiment|favorite|trader|deal/i.test(d)) console.log('%c▲ SENT','color:#f80',d);
      } } catch(e){}
      return _s.apply(this, arguments);
    };
    WebSocket.prototype.__hooked = true;
  }
  const O = window.__OrigWS || window.WebSocket; window.__OrigWS = O;
  const W = function(u,p){ const ws = p!==undefined ? new O(u,p) : new O(u);
    ws.addEventListener('message', ev => { const d = ev.data;
      if (typeof d==='string' && /^\[\[\s*"[^"]+"\s*,\s*\d{1,3}\s*\]\]$/.test(d.trim())) {
        window.__sentiment.push({t:Date.now(), d:d.trim()});
        console.log('%c▼ SENTIMENT?','color:#0f0', d.trim());
      } });
    return ws; };
  W.prototype = O.prototype; ['OPEN','CONNECTING','CLOSING','CLOSED'].forEach(k=>{try{W[k]=O[k]}catch(e){}});
  window.WebSocket = W;
  console.log('✅ Hooks armed. Switch asset a couple times, watch the sentiment bar.');
})();
```

Then switch asset 1–2× (fires the subscribe), let the bar update ~30s, and run
`copy(JSON.stringify({sent: window.__sent.slice(-80), sentiment: window.__sentiment.slice(-40)}, null, 1))`.

**Fallback if `__sent`/`__sentiment` stay empty** (socket runs in a Web Worker):
DevTools → Network → filter "WS" → click the `wss://…` connection → Messages tab;
read the frame sent on asset-switch + any short `[["SYMBOL",NN]]` received frames.

## The deliverable from the capture

1. The exact **outgoing** frame that enables traders'-sentiment (the real
   subscribe trigger).
2. Confirmation of the **incoming** sentiment frame format.
Then: replicate that trigger in `broker/sentiment_collector.py` /
`tools/po_sentiment_probe.py` and re-test in-bot capture.

## Other probe findings (not sentiment — already cataloged)

From `data/po_probe_report.json`: 140 assets (no sentiment field in metadata);
`get_candles_advanced` pages backward (unlimited history depth, 450+ contiguous
candles); `subscribe_symbol_timed(5s)` yields **real** OHLC (alt source to
`history()`); raw ticks ~2.35/s.
