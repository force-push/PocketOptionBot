"""Analyse broker-bot win-rate predictions vs PocketOption actual outcomes.

Usage
-----
    python3 tools/po_analysis.py                  # reads data/decisions.jsonl
    python3 tools/po_analysis.py --jsonl path/to/decisions.jsonl
    python3 tools/po_analysis.py --live           # also pulls PO closed-deals via API

Output (all to stdout)
------
    1. Overall trade summary
    2. Per-pair stats: predicted win rate, actual win rate, avg payout, EV
    3. Broker calibration: predicted win-rate bucket → actual win rate
    4. Payout distribution and break-even analysis
    5. EV per pair at current live payout (--live mode) or median observed payout
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from pathlib import Path


# ── helpers ───────────────────────────────────────────────────────────────────

def _wr_bucket(rate: float) -> str:
    """Map a 0–1 win rate to a display bucket label."""
    pct = rate * 100
    if pct < 77:
        return "<77%"
    elif pct < 79:
        return "77-79%"
    elif pct < 81:
        return "79-81%"
    elif pct < 83:
        return "81-83%"
    else:
        return "≥83%"


def _ev(win_rate: float, payout_pct: float) -> float:
    """Expected value per unit stake. Positive = profitable."""
    return win_rate * (payout_pct / 100) - (1 - win_rate)


def _break_even_wr(payout_pct: float) -> float:
    """Minimum win rate to achieve EV ≥ 0."""
    return 1 / (1 + payout_pct / 100)


# ── core analysis ─────────────────────────────────────────────────────────────

def analyse(rows: list[dict], live_payouts: dict[str, int] | None = None) -> None:
    trades = [
        r for r in rows
        if r.get("decision") == "TRADE" and r.get("outcome") in ("win", "loss")
    ]

    if not trades:
        print("No resolved TRADE rows found.")
        return

    wins = [r for r in trades if r["outcome"] == "win"]
    losses = [r for r in trades if r["outcome"] == "loss"]
    total = len(trades)
    overall_wr = len(wins) / total

    # Back-calculate payout from win pnl (unavailable for losses)
    def _calc_payout(r: dict) -> float | None:
        pp = r.get("payout_pct")
        if pp is not None:
            return float(pp)
        if r["outcome"] == "win" and r.get("pnl") and r.get("stake"):
            return r["pnl"] / r["stake"] * 100
        return None

    all_payouts = [p for r in trades if (p := _calc_payout(r)) is not None]
    median_payout = statistics.median(all_payouts) if all_payouts else 92.0

    # ── 1. Overall summary ────────────────────────────────────────────────────
    print("=" * 62)
    print("  PocketOption Bot — Broker vs Actual Analysis")
    print("=" * 62)
    print(f"  Resolved trades : {total}  ({len(wins)}W / {len(losses)}L)")
    print(f"  Overall win rate: {overall_wr:.1%}")
    print(f"  Median payout   : {median_payout:.1f}%")
    break_even = _break_even_wr(median_payout)
    ev_overall = _ev(overall_wr, median_payout)
    print(f"  Break-even WR @ {median_payout:.0f}%: {break_even:.1%}")
    print(f"  Overall EV      : {ev_overall:+.4f}  ({'POSITIVE ✓' if ev_overall >= 0 else 'NEGATIVE ✗'})")
    print()

    # ── 2. Per-pair stats ─────────────────────────────────────────────────────
    print("─" * 62)
    print("  Per-pair breakdown")
    print("─" * 62)
    pair_data: dict[str, dict] = defaultdict(lambda: {
        "wins": 0, "losses": 0, "bot_wrs": [], "payouts": []
    })
    for r in trades:
        p = r["pair_api"]
        pair_data[p]["wins" if r["outcome"] == "win" else "losses"] += 1
        pair_data[p]["bot_wrs"].append(r["bot_win_rate"])
        if (po := _calc_payout(r)) is not None:
            pair_data[p]["payouts"].append(po)

    print(f"  {'Pair':<18} {'N':>4}  {'ActWR':>6}  {'BotWR':>6}  {'Payout':>7}  {'EV':>7}  {'BE-WR':>6}")
    print(f"  {'-'*18} {'-'*4}  {'-'*6}  {'-'*6}  {'-'*7}  {'-'*7}  {'-'*6}")
    for pair in sorted(pair_data, key=lambda p: -(pair_data[p]["wins"] + pair_data[p]["losses"])):
        d = pair_data[pair]
        n = d["wins"] + d["losses"]
        actual_wr = d["wins"] / n
        avg_bot_wr = statistics.mean(d["bot_wrs"])
        payout = live_payouts.get(pair) if live_payouts else None
        if payout is None:
            payout = statistics.median(d["payouts"]) if d["payouts"] else median_payout
        ev = _ev(actual_wr, payout)
        be = _break_even_wr(payout)
        payout_src = "*" if (live_payouts and pair in live_payouts) else " "
        ev_flag = "✓" if ev >= 0 else "✗"
        print(f"  {pair:<18} {n:>4}  {actual_wr:>5.1%}  {avg_bot_wr:>5.1%}  {payout:>6.1f}%{payout_src} {ev:>+7.4f}{ev_flag} {be:>5.1%}")
    if live_payouts:
        print("  (* = live payout from PO API)")
    print()

    # ── 3. Broker calibration ─────────────────────────────────────────────────
    print("─" * 62)
    print("  Broker win-rate calibration (predicted vs actual)")
    print("─" * 62)
    buckets: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "bot_wrs": []})
    for r in trades:
        b = _wr_bucket(r["bot_win_rate"])
        buckets[b]["wins" if r["outcome"] == "win" else "losses"] += 1
        buckets[b]["bot_wrs"].append(r["bot_win_rate"])

    bucket_order = ["<77%", "77-79%", "79-81%", "81-83%", "≥83%"]
    print(f"  {'Bucket':<10} {'N':>4}  {'Predicted':>10}  {'Actual':>8}  {'Delta':>7}")
    print(f"  {'-'*10} {'-'*4}  {'-'*10}  {'-'*8}  {'-'*7}")
    for b in bucket_order:
        if b not in buckets:
            continue
        d = buckets[b]
        n = d["wins"] + d["losses"]
        actual = d["wins"] / n
        predicted = statistics.mean(d["bot_wrs"])
        delta = actual - predicted
        flag = "↑" if delta > 0.03 else ("↓" if delta < -0.03 else "≈")
        print(f"  {b:<10} {n:>4}  {predicted:>9.1%}  {actual:>7.1%}  {delta:>+6.1%} {flag}")
    print()

    # ── 4. Payout distribution ────────────────────────────────────────────────
    print("─" * 62)
    print("  Payout distribution (win trades only — back-calculated)")
    print("─" * 62)
    payout_buckets: dict[str, int] = defaultdict(int)
    for r in wins:
        po = _calc_payout(r)
        if po is None:
            continue
        if po < 60:
            payout_buckets["<60%"] += 1
        elif po < 75:
            payout_buckets["60-75%"] += 1
        elif po < 85:
            payout_buckets["75-85%"] += 1
        elif po < 92:
            payout_buckets["85-92%"] += 1
        else:
            payout_buckets["92%"] += 1

    for label in ["<60%", "60-75%", "75-85%", "85-92%", "92%"]:
        if label not in payout_buckets:
            continue
        cnt = payout_buckets[label]
        bar = "█" * (cnt // 2)
        print(f"  {label:<8} {cnt:>4}  {bar}")
    print()

    # ── 5. EV sensitivity ────────────────────────────────────────────────────
    print("─" * 62)
    print("  EV sensitivity — overall actual WR at different payouts")
    print("─" * 62)
    print(f"  Actual win rate: {overall_wr:.1%}")
    print()
    print(f"  {'Payout':>8}  {'EV':>8}  {'Profitable?':>12}  {'BE win rate':>12}")
    print(f"  {'-'*8}  {'-'*8}  {'-'*12}  {'-'*12}")
    for pct in [50, 60, 70, 80, 85, 90, 92, 95]:
        ev = _ev(overall_wr, pct)
        be = _break_even_wr(pct)
        flag = "YES ✓" if ev >= 0 else "NO  ✗"
        print(f"  {pct:>7}%  {ev:>+8.4f}  {flag:>12}  {be:>11.1%}")
    print()

    # ── 6. Recommendation ────────────────────────────────────────────────────
    print("─" * 62)
    print("  Summary & notes")
    print("─" * 62)
    best_pair = max(pair_data, key=lambda p: pair_data[p]["wins"] / (pair_data[p]["wins"] + pair_data[p]["losses"]))
    worst_pair = min(pair_data, key=lambda p: pair_data[p]["wins"] / (pair_data[p]["wins"] + pair_data[p]["losses"]))
    print(f"  Best pair  : {best_pair} ({pair_data[best_pair]['wins']/(pair_data[best_pair]['wins']+pair_data[best_pair]['losses']):.1%} WR)")
    print(f"  Worst pair : {worst_pair} ({pair_data[worst_pair]['wins']/(pair_data[worst_pair]['wins']+pair_data[worst_pair]['losses']):.1%} WR)")

    if all_payouts:
        low_payout_count = sum(1 for p in all_payouts if p < 80)
        if low_payout_count:
            print(f"  ⚠  {low_payout_count} win trades had payout <80% — "
                  f"these erode EV significantly. MIN_PAYOUT_PCT=80 would filter them.")

    # Calibration verdict
    all_predicted = [r["bot_win_rate"] for r in trades]
    avg_predicted = statistics.mean(all_predicted)
    calibration_delta = overall_wr - avg_predicted
    print(f"  Broker avg predicted WR: {avg_predicted:.1%} | Actual: {overall_wr:.1%} | Delta: {calibration_delta:+.1%}")
    if abs(calibration_delta) < 0.05:
        print("  Broker is reasonably well-calibrated (delta <5%)")
    elif calibration_delta < 0:
        print("  ⚠  Broker OVER-predicts win rate — actual results lag prediction")
    else:
        print("  ✓  Broker UNDER-predicts — actual results beat prediction")
    print("=" * 62)


# ── async live-payout fetch ───────────────────────────────────────────────────

async def _fetch_live_payouts() -> dict[str, int]:
    """Connect to PO API and return {symbol: payout_pct} for active pairs."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from config.settings import settings
    from broker.po_api import PocketOptionAPIClient

    if not settings.po_ssid:
        print("  [live mode] No PO_SSID configured — skipping live payout fetch")
        return {}

    client = PocketOptionAPIClient(ssid=settings.po_ssid)
    try:
        await client.connect()
        active = await client.get_active_pairs()
        return {a["symbol"]: a["payout"] for a in active if a.get("payout") is not None}
    except Exception as exc:
        print(f"  [live mode] Could not fetch payouts: {exc}")
        return {}


# ── entrypoint ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Broker vs PO win-rate analysis")
    parser.add_argument("--jsonl", default="data/decisions.jsonl",
                        help="Path to decisions.jsonl (default: data/decisions.jsonl)")
    parser.add_argument("--live", action="store_true",
                        help="Fetch live payouts from PO API (requires PO_SSID in .env)")
    args = parser.parse_args()

    path = Path(args.jsonl)
    if not path.exists():
        print(f"Not found: {path}")
        return

    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    live_payouts = asyncio.run(_fetch_live_payouts()) if args.live else None

    analyse(rows, live_payouts=live_payouts)


if __name__ == "__main__":
    main()
