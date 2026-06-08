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
    shadow: bool = False                # True if traded only to collect data (would_skip_reason set)
    would_skip_reason: str | None = None  # gate that WOULD have skipped this in normal mode
    payout_pct: int | None = None
    trade_id: str | None = None
    status: str = "PENDING"
    outcome: str | None = None  # "win" | "loss" | "draw"
    pnl: float | None = None
    pnl_currency: str | None = None
    balance_before: float | None = None
    balance_after: float | None = None
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def write_decision(path: str | Path, row: DecisionRow) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(row), default=str, ensure_ascii=False) + "\n")


def backfill_outcome(path: str | Path, trade_id: str, outcome: str, pnl: float,
                     balance_before: float | None = None, balance_after: float | None = None,
                     pnl_currency: str | None = None) -> bool:
    """Rewrite the row whose trade_id matches, filling outcome fields. Returns True if found."""
    p = Path(path)
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
        with p.open("w", encoding="utf-8") as fh:
            for rec in rows:
                fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
    return found
