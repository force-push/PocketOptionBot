#!/usr/bin/env python3
"""Seed realistic synthetic dashboard data — NO network/SSID/Telegram needed.

Writes:
- ``data/decisions.jsonl`` : a time series of resolved TRADEs (wins/losses/draws)
  plus some SKIPs, across varied pairs / directions / expiries. Rows match
  ``strategy.trade_logger.DecisionRow`` so analytics + the UI consume them as-is.
- ``data/live_state.json`` : a snapshot with a few active trades (future expiries)
  so the Active Trades column and KPI strip render.

Deterministic: fixed RNG seed for reproducible review screenshots.

Usage::

    python3 tools/dashboard_demo.py
    python3 tools/dashboard_demo.py --count 80 --out data
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

PAIRS = [
    ("EUR/USD OTC", "EURUSD_otc"),
    ("GBP/USD OTC", "GBPUSD_otc"),
    ("USD/JPY", "USDJPY"),
    ("AUD/CAD OTC", "AUDCAD_otc"),
    ("EUR/GBP OTC", "EURGBP_otc"),
    ("USD/CHF", "USDCHF"),
    ("GBP/JPY OTC", "GBPJPY_otc"),
    ("NZD/USD OTC", "NZDUSD_otc"),
    ("AUD/USD OTC", "AUDUSD_otc"),
]
EXPIRIES = [5, 15, 30, 60]
DIRECTIONS = ["CALL", "PUT"]
SKIP_REASONS = [
    "direction_disagreement",
    "confluence_below_floor",
    "no_confluence_direction",
    "risk_blocked",
]
PAYOUT = 0.92  # win returns stake * payout as profit


def _row_base(cid, pair_raw, pair_api, direction, expiry, conf, bot_wr, ts, stake):
    """A DecisionRow-shaped dict (mirrors strategy/trade_logger.DecisionRow)."""
    return {
        "cycle_id": cid,
        "pair_raw": pair_raw,
        "pair_api": pair_api,
        "bot_win_rate": round(bot_wr, 4),
        "bot_is_top_pick": True,
        "bot_direction": direction,
        "bot_setup": "trend-continuation",
        "bot_indicators_raw": "RSI/MACD/EMA aligned",
        "our_direction": direction,
        "our_confluence_score": round(conf, 4),
        "our_signal_breakdown": {"rsi": [direction, 0.8], "macd": [direction, 0.7]},
        "agreement": True,
        "combined_probability": round((conf + bot_wr) / 2, 4),
        "expiry_seconds": expiry,
        "decision": "TRADE",
        "skip_reason": None,
        "stake": stake,
        "trade_id": None,
        "status": "PENDING",
        "outcome": None,
        "pnl": None,
        "pnl_currency": "USD",
        "balance_before": None,
        "balance_after": None,
        "ts": ts.isoformat(),
    }


def generate(count: int, *, seed: int = 1337, stake: float = 1.50) -> tuple[list[dict], dict]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    # spread history over the last ~6 hours, oldest first
    start = now - timedelta(hours=6)
    rows: list[dict] = []
    balance = 1000.0
    cum_for_state = 0.0

    for i in range(count):
        # decision time, monotonically increasing with jitter
        ts = start + timedelta(seconds=int(i * (6 * 3600 / max(count, 1))) + rng.randint(0, 90))
        cid = f"{ts.strftime('%Y%m%dT%H%M%S')}-{i:04d}"
        pair_raw, pair_api = rng.choice(PAIRS)
        direction = rng.choice(DIRECTIONS)
        expiry = rng.choice(EXPIRIES)
        bot_wr = rng.uniform(0.80, 0.90)

        # ~25% skips
        if rng.random() < 0.25:
            conf = rng.uniform(0.55, 0.74)
            row = _row_base(cid, pair_raw, pair_api, direction, expiry, conf, bot_wr, ts, stake)
            row["decision"] = "SKIP"
            row["skip_reason"] = rng.choice(SKIP_REASONS)
            row["status"] = "SKIP"
            rows.append(row)
            continue

        conf = rng.uniform(0.75, 0.90)
        row = _row_base(cid, pair_raw, pair_api, direction, expiry, conf, bot_wr, ts, stake)
        row["trade_id"] = f"demo-{i:05d}"

        # outcome: ~60% win, ~36% loss, ~4% draw
        r = rng.random()
        if r < 0.60:
            outcome, pnl = "win", round(stake * PAYOUT, 2)
        elif r < 0.96:
            outcome, pnl = "loss", round(-stake, 2)
        else:
            outcome, pnl = "draw", 0.0

        bal_before = round(balance, 2)
        balance += pnl
        cum_for_state += pnl
        row.update(
            status=outcome.upper(),
            outcome=outcome,
            pnl=pnl,
            balance_before=bal_before,
            balance_after=round(balance, 2),
        )
        rows.append(row)

    # ── a few ACTIVE trades (future expiries) for live_state.json ─────────────
    active = []
    for j in range(3):
        pair_raw, pair_api = PAIRS[j]
        direction = DIRECTIONS[j % 2]
        expiry = EXPIRIES[(j + 1) % len(EXPIRIES)]
        opened = now - timedelta(seconds=rng.randint(2, expiry - 2 if expiry > 4 else 1))
        active.append({
            "trade_id": f"active-{j}",
            "pair_raw": pair_raw,
            "pair_api": pair_api,
            "dir": direction,
            "stake": stake,
            "entry": round(rng.uniform(0.6, 1.9), 5),
            "opened_at": opened.isoformat(),
            "expiry_at": (opened + timedelta(seconds=expiry)).isoformat(),
            "expiry_seconds": expiry,
            "confluence_n": rng.randint(3, 5),
            "confluence_score": round(rng.uniform(0.76, 0.9), 2),
        })

    live_state = {
        "mode": "DEMO",
        "dry_run": True,
        "connected": True,
        "balance": round(balance, 2),
        "currency": "USD",
        "active": active,
        "last_cycle": {"cycle_id": rows[-1]["cycle_id"] if rows else None,
                       "status": "trading", "skip_reason": None},
        "risk_block_reason": None,
        "ts": now.isoformat(),
    }
    return rows, live_state


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed synthetic dashboard data")
    ap.add_argument("--count", type=int, default=60, help="number of decision rows")
    ap.add_argument("--seed", type=int, default=1337, help="RNG seed")
    ap.add_argument("--out", default=str(_PROJECT_ROOT / "data"),
                    help="output directory (default: <repo>/data)")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = out_dir / "decisions.jsonl"
    state_path = out_dir / "live_state.json"

    rows, live_state = generate(args.count, seed=args.seed)

    with decisions_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    state_path.write_text(json.dumps(live_state, indent=2, ensure_ascii=False), encoding="utf-8")

    trades = sum(1 for r in rows if r["decision"] == "TRADE")
    skips = len(rows) - trades
    wins = sum(1 for r in rows if r.get("outcome") == "win")
    losses = sum(1 for r in rows if r.get("outcome") == "loss")
    draws = sum(1 for r in rows if r.get("outcome") == "draw")
    print(f"Wrote {len(rows)} rows → {decisions_path}")
    print(f"  TRADE={trades} (W{wins}/L{losses}/D{draws})  SKIP={skips}")
    print(f"Wrote live_state ({len(live_state['active'])} active, "
          f"balance={live_state['balance']}) → {state_path}")


if __name__ == "__main__":
    main()
