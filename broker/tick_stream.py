"""Raw-tick accumulator: build 1s OHLC bars from PocketOption's tick stream.

PocketOption pushes raw price ticks via the WS connection at ~500ms cadence.
The format received from `api.create_raw_handler().wait_next()` is:

    Python list: [["SYMBOL", server_epoch, price_float]]   (server epoch = UTC + 7200s)
    String:      '{"asset":"SYM","period":1,"history":[[epoch,price],...}' — sent once
                  immediately after a changeSymbol subscription (history seed).

`process(raw)` is synchronous — call it inside the async polling loop.  It
returns a completed-bar DataFrame (o/h/l/c/v, DatetimeIndex UTC) the instant a
second boundary rolls, so the caller can run evaluate_flip() with ~0-500ms lag
vs the FlipStreamer's ~1-2s bar-close lag.
"""
from __future__ import annotations

import json
from collections import deque
from typing import Any

import pandas as pd

_EPOCH_OFFSET = 7200  # server epoch = UTC + 7200 s


class TickAccumulator:
    """Accumulate raw WS tick frames into 1s OHLC bars for one pair.

    Usage::
        acc = TickAccumulator("EURUSD_otc")
        acc.seed_df(seed_dataframe)          # pre-warm from history()
        ...
        async for raw in handler:
            df = acc.process(raw)            # returns DataFrame on bar-close, else None
            if df is not None:
                result = evaluate_flip(df, params)
    """

    def __init__(self, pair: str, history_bars: int = 200) -> None:
        self._pair = pair
        self._history_bars = history_bars
        self._bars: dict[int, dict] = {}      # sec_key → {o, h, l, c, n}
        self._bar_order: deque[int] = deque()  # insertion order for pruning + to_df()
        self._current_sec: int | None = None

    # ── seeding ──────────────────────────────────────────────────────────────

    def seed_df(self, df: pd.DataFrame) -> None:
        """Pre-populate from an existing o/h/l/c/v DataFrame (e.g. from history()).

        The DataFrame's DatetimeIndex must be UTC.  Existing bars are overwritten
        so the most-recent seed always wins.  Call before starting the tick loop.
        """
        for ts, row in df.iterrows():
            sec = int(pd.Timestamp(ts).timestamp())
            self._insert(sec, {
                "o": float(row["o"]), "h": float(row["h"]),
                "l": float(row["l"]), "c": float(row["c"]),
                "n": max(1, int(row.get("v", 1))),
            })

    # ── main tick processor ───────────────────────────────────────────────────

    def process(self, raw: Any) -> pd.DataFrame | None:
        """Feed one raw WS frame.

        Returns a completed-bar DataFrame when the second rolls over (the
        previous second's bar just closed).  Returns None for all other frames
        (mid-second tick, history-seed string, deal/balance frames, etc.).
        """
        # ── history-seed string: {"asset":"SYM","period":1,"history":[[ep,px],...]}
        if isinstance(raw, str) and '"history"' in raw:
            self._parse_history_string(raw)
            return None

        # ── tick frame: Python list [["SYM", server_epoch, price]] ───────────
        if (isinstance(raw, list) and len(raw) == 1
                and isinstance(raw[0], (list, tuple)) and len(raw[0]) == 3):
            sym, epoch_raw, price_raw = raw[0]
            if not isinstance(sym, str) or sym != self._pair:
                return None
            ts = float(epoch_raw) - _EPOCH_OFFSET  # normalise to UTC
            return self._update(ts, float(price_raw))

        return None

    # ── internal ─────────────────────────────────────────────────────────────

    def _parse_history_string(self, raw: str) -> None:
        """Parse the history-seed JSON string sent right after changeSymbol."""
        try:
            data = json.loads(raw) if raw.strip().startswith("{") else None
            if not data or data.get("asset") != self._pair:
                return
            for item in data.get("history") or []:
                if len(item) >= 2:
                    ts = float(item[0]) - _EPOCH_OFFSET
                    px = float(item[1])
                    sec = int(ts)
                    self._insert(sec, {"o": px, "h": px, "l": px, "c": px, "n": 1})
        except Exception:
            pass

    def _update(self, ts: float, price: float) -> pd.DataFrame | None:
        """Update the live bar; return a closed DataFrame when the second rolls."""
        sec = int(ts)
        rolled = self._current_sec is not None and sec > self._current_sec
        self._current_sec = sec

        b = self._bars.get(sec)
        if b is None:
            b = {"o": price, "h": price, "l": price, "c": price, "n": 0}
            self._bars[sec] = b
            self._bar_order.append(sec)
            while len(self._bar_order) > self._history_bars:
                old = self._bar_order.popleft()
                self._bars.pop(old, None)
        else:
            if price > b["h"]:
                b["h"] = price
            if price < b["l"]:
                b["l"] = price
            b["c"] = price
        b["n"] += 1

        if rolled:
            return self.to_df()
        return None

    def _insert(self, sec: int, bar: dict) -> None:
        if sec not in self._bars:
            self._bars[sec] = bar
            self._bar_order.append(sec)
            while len(self._bar_order) > self._history_bars:
                old = self._bar_order.popleft()
                self._bars.pop(old, None)
        else:
            self._bars[sec].update(bar)

    def to_df(self) -> pd.DataFrame | None:
        """Build a completed-bar DataFrame (excludes the current open second).

        Returns None if fewer than 2 completed bars exist.  The returned
        DataFrame matches the o/h/l/c/v DatetimeIndex(UTC) shape expected by
        evaluate_flip().
        """
        keys = sorted(self._bar_order)
        if len(keys) < 2:
            return None
        completed = keys[:-1]  # exclude the currently-open second
        rows = []
        for k in completed:
            b = self._bars.get(k)
            if b:
                rows.append({
                    "date": pd.Timestamp(k, unit="s", tz="UTC"),
                    "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"],
                    "v": float(b["n"]),
                })
        if not rows:
            return None
        df = pd.DataFrame(rows).set_index("date")
        df.index = pd.DatetimeIndex(df.index)
        return df
