#!/usr/bin/env python3
"""Offline regime-surface research over resolved Argus trades.

This is a research-only approximation of the "momentum x volatility regime
surface" idea from the Quant Decoded reels. It does not change live trading.

Inputs are strictly pre-entry metrics already stamped on DecisionRow:
ATR bps, Bollinger width bps, ADX/DI, RSI, MACD gap expansion/std, trend age,
entry kind, direction, pair, expiry, outcome and P&L.

Usage:
    python3 tools/analyze_regime_surface.py --hours 48
    python3 tools/analyze_regime_surface.py --all
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "decisions.db"
REPORT = ROOT / "reports" / "regime_surface_report.md"

BREAKEVEN = 1.0 / 1.92
DEFAULT_WIN_PNL = 1.38
DEFAULT_LOSS_PNL = -1.50


@dataclass(frozen=True)
class Trade:
    ts: datetime
    pair: str
    direction: str
    expiry: int | None
    entry_kind: str
    outcome: str
    pnl: float
    metrics: dict[str, Any]
    features: dict[str, float]
    vol_bucket: str
    momentum_bucket: str
    shock_bucket: str
    regime: str


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        x = float(value)
        if math.isnan(x) or math.isinf(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def _parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _pnl(outcome: str, value: Any) -> float:
    p = _num(value)
    if p is not None:
        return p
    if outcome == "win":
        return DEFAULT_WIN_PNL
    if outcome == "loss":
        return DEFAULT_LOSS_PNL
    return 0.0


def _quantiles(values: Iterable[float]) -> dict[str, float]:
    vals = sorted(v for v in values if v is not None and not math.isnan(v))
    if not vals:
        return {"p25": 0.0, "p50": 0.0, "p75": 0.0}

    def q(p: float) -> float:
        if len(vals) == 1:
            return vals[0]
        pos = (len(vals) - 1) * p
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return vals[lo]
        return vals[lo] + (vals[hi] - vals[lo]) * (pos - lo)

    return {"p25": q(0.25), "p50": q(0.50), "p75": q(0.75)}


def _bucket(value: float, qs: dict[str, float], labels: tuple[str, str, str, str]) -> str:
    if value <= qs["p25"]:
        return labels[0]
    if value <= qs["p50"]:
        return labels[1]
    if value <= qs["p75"]:
        return labels[2]
    return labels[3]


def _stats(rows: list[Trade]) -> dict[str, float]:
    n = len(rows)
    if not n:
        return {"n": 0, "wr": 0.0, "pnl": 0.0, "avg": 0.0}
    wins = sum(1 for r in rows if r.outcome in ("win", "draw"))
    pnl = sum(r.pnl for r in rows)
    return {
        "n": n,
        "wr": wins / n,
        "pnl": pnl,
        "avg": pnl / n,
    }


def _format_stats(rows: list[Trade]) -> str:
    s = _stats(rows)
    wr = s["wr"] * 100.0
    verdict = ""
    if s["n"] >= 30:
        wr_good = s["wr"] >= BREAKEVEN + 0.02
        wr_bad = s["wr"] <= BREAKEVEN - 0.02
        pnl_good = s["pnl"] > 0
        pnl_bad = s["pnl"] < 0
        if wr_good and pnl_good:
            verdict = "KEEP?"
        elif wr_bad and pnl_bad:
            verdict = "KILL?"
        elif wr_bad != pnl_bad:
            # Variable stake and martingale can make WR and realised PnL disagree.
            verdict = "MIXED"
    return f"{s['n']:4.0f} | {wr:5.1f}% | ${s['pnl']:+7.2f} | ${s['avg']:+6.3f} | {verdict}"


def _load_base_rows(db: Path, hours: float | None) -> list[dict[str, Any]]:
    where = "decision = 'TRADE' AND shadow = 0 AND outcome IN ('win','loss','draw')"
    params: tuple[Any, ...] = ()
    if hours is not None:
        where += " AND replace(substr(ts,1,19),'T',' ') > datetime('now', ?)"
        params = (f"-{hours} hours",)

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"""
            SELECT ts, pair_api, our_direction, expiry_seconds, outcome, pnl,
                   json_extract(data,'$.flip_metrics') AS flip_metrics
            FROM decisions
            WHERE {where}
            ORDER BY ts ASC
            """,
            params,
        ).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def _derive_features(row: dict[str, Any]) -> dict[str, float] | None:
    try:
        metrics = json.loads(row.get("flip_metrics") or "{}")
    except json.JSONDecodeError:
        metrics = {}
    if not metrics:
        return None

    direction = (row.get("our_direction") or "").upper()
    sign = 1.0 if direction == "CALL" else -1.0 if direction == "PUT" else 0.0

    plus_di = _num(metrics.get("plus_di"), 0.0) or 0.0
    minus_di = _num(metrics.get("minus_di"), 0.0) or 0.0
    di_denom = max(plus_di + minus_di, 1e-9)
    di_aligned = sign * ((plus_di - minus_di) / di_denom)

    rsi = _num(metrics.get("rsi"), 50.0) or 50.0
    rsi_aligned = sign * ((rsi - 50.0) / 50.0)

    atr_bps = _num(metrics.get("atr_bps"), 0.0) or 0.0
    bb_width_bps = _num(metrics.get("bb_width_bps"), 0.0) or 0.0
    macd_gap_std = _num(metrics.get("macd_gap_std"), 0.0) or 0.0
    gap_expansion = _num(metrics.get("gap_expansion"), 0.0) or 0.0
    macd_consistency = _num(metrics.get("macd_sign_consistency"), 0.5) or 0.5
    adx = _num(metrics.get("adx"), 0.0) or 0.0
    bars = max(_num(metrics.get("bars_in_trend"), 0.0) or 0.0, 0.0)

    # Features are deliberately simple and explainable. Percentile bucketing is
    # done after loading the sample, so these raw values stay audit-friendly.
    momentum_pressure = (
        0.34 * di_aligned
        + 0.22 * rsi_aligned
        + 0.18 * gap_expansion
        + 0.16 * (macd_consistency - 0.5)
        + 0.10 * min(math.log1p(bars) / math.log(60), 1.0)
    )
    volatility_pressure = (
        0.42 * math.log1p(max(atr_bps, 0.0))
        + 0.32 * math.log1p(max(bb_width_bps, 0.0))
        + 0.16 * math.log1p(max(macd_gap_std, 0.0))
        + 0.10 * min(adx / 80.0, 1.0)
    )
    shock_pressure = (
        0.50 * math.log1p(max(atr_bps, 0.0))
        + 0.30 * max(gap_expansion, 0.0)
        + 0.20 * math.log1p(max(macd_gap_std, 0.0))
    )

    return {
        "di_aligned": di_aligned,
        "rsi_aligned": rsi_aligned,
        "atr_bps": atr_bps,
        "bb_width_bps": bb_width_bps,
        "macd_gap_std": macd_gap_std,
        "gap_expansion": gap_expansion,
        "macd_consistency": macd_consistency,
        "adx": adx,
        "bars_in_trend": bars,
        "momentum_pressure": momentum_pressure,
        "volatility_pressure": volatility_pressure,
        "shock_pressure": shock_pressure,
    }


def _regime(momentum_bucket: str, vol_bucket: str, shock_bucket: str, metrics: dict[str, Any]) -> str:
    entry_kind = str(metrics.get("entry_kind") or "?")
    if shock_bucket == "shock-high" and momentum_bucket in ("mom-against", "mom-neutral"):
        return "shock_chop_or_fade"
    if shock_bucket == "shock-high" and momentum_bucket in ("mom-aligned", "mom-extended"):
        return "shock_trend_follow"
    if vol_bucket in ("vol-low", "vol-midlow") and momentum_bucket in ("mom-aligned", "mom-extended"):
        return "clean_trend_low_vol"
    if vol_bucket == "vol-low" and momentum_bucket in ("mom-against", "mom-neutral"):
        return "calm_compression"
    if vol_bucket == "vol-high" and momentum_bucket == "mom-extended":
        return "extended_high_vol"
    if entry_kind == "trend" and momentum_bucket in ("mom-against", "mom-neutral"):
        return "weak_continuation"
    return f"{vol_bucket}_{momentum_bucket}"


def build_trades(rows: list[dict[str, Any]]) -> list[Trade]:
    prepared: list[tuple[dict[str, Any], dict[str, float], dict[str, Any]]] = []
    for row in rows:
        features = _derive_features(row)
        if features is None:
            continue
        try:
            metrics = json.loads(row.get("flip_metrics") or "{}")
        except json.JSONDecodeError:
            metrics = {}
        prepared.append((row, features, metrics))

    vol_q = _quantiles(f["volatility_pressure"] for _, f, _ in prepared)
    mom_q = _quantiles(f["momentum_pressure"] for _, f, _ in prepared)
    shock_q = _quantiles(f["shock_pressure"] for _, f, _ in prepared)

    trades: list[Trade] = []
    for row, features, metrics in prepared:
        vol_bucket = _bucket(
            features["volatility_pressure"],
            vol_q,
            ("vol-low", "vol-midlow", "vol-midhigh", "vol-high"),
        )
        momentum_bucket = _bucket(
            features["momentum_pressure"],
            mom_q,
            ("mom-against", "mom-neutral", "mom-aligned", "mom-extended"),
        )
        shock_bucket = _bucket(
            features["shock_pressure"],
            shock_q,
            ("shock-low", "shock-midlow", "shock-midhigh", "shock-high"),
        )
        trades.append(
            Trade(
                ts=_parse_ts(row["ts"]),
                pair=row.get("pair_api") or "?",
                direction=(row.get("our_direction") or "?").upper(),
                expiry=int(row["expiry_seconds"]) if row.get("expiry_seconds") is not None else None,
                entry_kind=str(metrics.get("entry_kind") or "?"),
                outcome=str(row.get("outcome") or "").lower(),
                pnl=_pnl(str(row.get("outcome") or "").lower(), row.get("pnl")),
                metrics=metrics,
                features=features,
                vol_bucket=vol_bucket,
                momentum_bucket=momentum_bucket,
                shock_bucket=shock_bucket,
                regime=_regime(momentum_bucket, vol_bucket, shock_bucket, metrics),
            )
        )
    return trades


def _group(rows: list[Trade], key) -> dict[Any, list[Trade]]:
    out: dict[Any, list[Trade]] = defaultdict(list)
    for row in rows:
        out[key(row)].append(row)
    return dict(out)


def _table(title: str, groups: dict[Any, list[Trade]], *, min_n: int, limit: int | None = None) -> list[str]:
    ranked = sorted(groups.items(), key=lambda kv: (_stats(kv[1])["pnl"], _stats(kv[1])["n"]), reverse=True)
    if limit is not None:
        ranked = ranked[:limit]
    lines = [f"## {title}", "", "bucket | n | WR | PnL | avg/trade | note", "--- | ---: | ---: | ---: | ---: | ---"]
    for label, rows in ranked:
        if len(rows) < min_n:
            continue
        lines.append(f"{label} | {_format_stats(rows)}")
    if len(lines) == 3:
        lines.append(f"_No bucket reached min_n={min_n}._")
    lines.append("")
    return lines


def write_report(trades: list[Trade], out: Path, *, scope: str, min_n: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    all_stats = _stats(trades)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines: list[str] = [
        "# Regime Surface Research",
        "",
        f"Generated: {now}",
        f"Scope: {scope}",
        "",
        "Research-only. This report reads resolved real trades from `data/decisions.db` and does not change live policy.",
        "",
        "## Headline",
        "",
        f"- Trades analysed: {all_stats['n']:.0f}",
        f"- Win rate: {all_stats['wr'] * 100:.1f}% vs break-even {BREAKEVEN * 100:.1f}%",
        f"- PnL: ${all_stats['pnl']:+.2f}",
        f"- Avg/trade: ${all_stats['avg']:+.3f}",
        "",
        "## Feature Construction",
        "",
        "- Momentum pressure: direction-aligned DI imbalance, RSI, MACD gap expansion, MACD sign consistency, trend age.",
        "- Volatility pressure: ATR bps, Bollinger width bps, MACD gap std, ADX.",
        "- Shock pressure: ATR bps + positive gap expansion + MACD instability.",
        "- Buckets are quartiles within the analysed sample, so labels are relative to current Argus history.",
        "",
    ]

    lines.extend(_table("Regime Label", _group(trades, lambda r: r.regime), min_n=min_n))
    lines.extend(_table("Volatility x Momentum Surface", _group(trades, lambda r: f"{r.vol_bucket} / {r.momentum_bucket}"), min_n=min_n))
    lines.extend(_table("Shock x Entry Kind", _group(trades, lambda r: f"{r.shock_bucket} / {r.entry_kind}"), min_n=min_n))
    lines.extend(_table("Regime x Direction", _group(trades, lambda r: f"{r.regime} / {r.direction}"), min_n=min_n))
    lines.extend(_table("Regime x Entry Kind", _group(trades, lambda r: f"{r.regime} / {r.entry_kind}"), min_n=min_n))

    # Pair-aware candidates: this is where actual tradability usually lives.
    pair_regime = _group(trades, lambda r: f"{r.pair} / {r.regime}")
    lines.extend(_table("Pair x Regime Candidates", pair_regime, min_n=max(10, min_n // 2), limit=30))

    hour_regime = _group(trades, lambda r: f"{r.ts.hour:02d}Z / {r.regime}")
    lines.extend(_table("UTC Hour x Regime Candidates", hour_regime, min_n=max(10, min_n // 2), limit=30))

    strong = []
    weak = []
    for label, rows in pair_regime.items():
        s = _stats(rows)
        if s["n"] >= min_n and s["pnl"] > 0 and s["wr"] >= BREAKEVEN + 0.04:
            strong.append((label, s))
        if s["n"] >= min_n and s["pnl"] < 0 and s["wr"] <= BREAKEVEN - 0.04:
            weak.append((label, s))
    strong.sort(key=lambda x: (x[1]["pnl"], x[1]["n"]), reverse=True)
    weak.sort(key=lambda x: (x[1]["pnl"], -x[1]["n"]))

    lines.extend([
        "## Interpretation",
        "",
        "Promote nothing from this report directly into live trading. Treat positive buckets as hypotheses for a shadow gate or a locked walk-forward test.",
        "",
        "Strong pair/regime hypotheses:",
    ])
    if strong:
        for label, s in strong[:10]:
            lines.append(f"- {label}: n={s['n']:.0f}, WR={s['wr']*100:.1f}%, PnL=${s['pnl']:+.2f}")
    else:
        lines.append("- None reached the guardrail.")

    lines.append("")
    lines.append("Weak pair/regime avoid-list candidates:")
    if weak:
        for label, s in weak[:10]:
            lines.append(f"- {label}: n={s['n']:.0f}, WR={s['wr']*100:.1f}%, PnL=${s['pnl']:+.2f}")
    else:
        lines.append("- None reached the guardrail.")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DB)
    ap.add_argument("--out", type=Path, default=REPORT)
    ap.add_argument("--hours", type=float, default=48.0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--min-n", type=int, default=30)
    args = ap.parse_args()

    hours = None if args.all else args.hours
    scope = "all history" if hours is None else f"last {hours:g}h"
    rows = _load_base_rows(args.db, hours)
    trades = build_trades(rows)
    write_report(trades, args.out, scope=scope, min_n=args.min_n)

    s = _stats(trades)
    print(f"Wrote {args.out}")
    print(f"{scope}: n={s['n']:.0f} WR={s['wr']*100:.1f}% PnL=${s['pnl']:+.2f}")


if __name__ == "__main__":
    main()
