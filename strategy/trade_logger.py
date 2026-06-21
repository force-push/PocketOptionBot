# strategy/trade_logger.py
"""Append/backfill structured decision rows to data/decisions.jsonl for learning."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class DecisionRow:
    cycle_id: str
    pair_raw: str
    pair_api: str
    bot_win_rate: float
    bot_is_top_pick: bool
    bot_direction: str
    bot_setup: str
    bot_indicators_raw: str
    our_direction: str | None
    our_confluence_score: float
    our_signal_breakdown: dict[str, Any]
    agreement: bool
    combined_probability: float       # heuristic confidence: mean(bot_win_rate, our_confluence)
    expiry_seconds: int
    decision: str               # "TRADE" | "SKIP"
    skip_reason: str | None
    stake: float
    calibrated_probability: float | None = None  # learned P(win); None until a model exists
    signal_assessment: dict | None = None         # entry-quality features, penalties, and TA notes
    shadow: bool = False                # True if traded only to collect data (would_skip_reason set)
    would_skip_reason: str | None = None  # gate that WOULD have skipped this in normal mode
    shadow_kind: str | None = None        # "expiry" = shadow expiry experiment; None = gate-override shadow
    sentiment: int | None = None          # 0-100 crowd buy% at decision time (None = not yet collected)
    payout_pct: int | None = None
    flip_metrics: dict | None = None      # flip-strategy diagnostics (entry_kind, adx,
                                          # plus/minus_di, dist_atr, macd_gap) for loss analysis
    flip_levers: dict | None = None       # active lever thresholds at decision time
                                          # (live-tunable; recorded per trade for review)
    trade_id: str | None = None
    status: str = "PENDING"
    outcome: str | None = None  # "win" | "loss" | "draw"
    pnl: float | None = None
    pnl_currency: str | None = None
    balance_before: float | None = None
    balance_after: float | None = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def write_decision(path: str | Path, row: DecisionRow) -> None:
    """Append a decision row. ``.db`` path → SQLite store; else legacy JSONL.

    The store is the live data path (see data/decisions_store.py). JSONL writing
    is retained for tests and any legacy/archive use, selected by file suffix.
    """
    p = Path(path)
    if str(p).endswith(".db"):
        from data.decisions_store import insert_decision
        insert_decision(p, asdict(row))
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(row), default=str, ensure_ascii=False) + "\n")


def backfill_outcome(path: str | Path, trade_id: str, outcome: str, pnl: float,
                     balance_before: float | None = None, balance_after: float | None = None,
                     pnl_currency: str | None = None) -> bool:
    """Fill outcome fields on the row whose trade_id matches. Returns True if found.

    ``.db`` path → one indexed UPDATE in the SQLite store (no rewrite). Else the
    legacy JSONL atomic-rewrite path (O(N), retained for tests/archive).
    """
    p = Path(path)
    if str(p).endswith(".db"):
        from data.decisions_store import update_outcome
        return update_outcome(p, trade_id, outcome, pnl,
                              balance_before=balance_before, balance_after=balance_after,
                              pnl_currency=pnl_currency)
    if not p.exists():
        return False
    rows = [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    found = False
    for rec in rows:
        if rec.get("trade_id") == trade_id:
            rec.update(status=outcome.upper(), outcome=outcome, pnl=pnl,
                       balance_before=balance_before, balance_after=balance_after,
                       pnl_currency=pnl_currency)
            found = True
    if found:
        # Atomic rewrite: temp file in the same dir, then os.replace. The old
        # in-place open("w") truncated first and wrote line-by-line — a kill
        # mid-write permanently destroyed every record after the cursor
        # (~10k records lost 2026-06-11 during supervisor kill/restarts).
        import os
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".decisions.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for rec in rows:
                    fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, p)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            raise
    return found
