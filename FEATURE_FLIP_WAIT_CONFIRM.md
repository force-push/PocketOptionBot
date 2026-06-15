# Feature: Flip wait-and-confirm + reversal-strength capture

**Branch:** `feat/flip-wait-confirm` · **Date:** 2026-06-15 · **Mode:** flip

## Problem

Flip entries fired at the **exact SuperTrend turn** (`bars_in_trend` 1-3). A manual
trader doesn't do this — they wait a few ticks for MACD/ADX to *confirm* the
reversal before entering. Entering at the turn is entering before the confirmation
exists.

This is measurable. At the turn the MACD gap is ~0 by construction (the line has
only just crossed the signal), and it opens up over the next few seconds:

| bars after flip | avg MACD gap / ATR |
|---|---|
| 1-3 (the turn)  | 0.56 – 0.59 |
| 4-9 (confirmation window) | 0.64 – **0.75** |
| 13+ | fades back |

So the flip path was reading the reversal-strength signal **at the one moment it
carries no information**. This is plausibly why flips and continuations perform
similarly in our data despite the flip being the "earlier" signal — the
continuation already enters *after* confirmation has built.

## What the data did and didn't support

Backtested on 389 resolved all-time flips (`decisions.db`):

- **Static MACD gap is NOT a useful flip filter.** Split at 0.6: gap<0.6 = 50.6%
  WR, gap 0.6-1.0 = 50.4%. Identical. Only 5 flips ever exceeded gap≥1.0 — a wide
  static gap at a *fresh* flip barely exists, so gating on it would erase flips.
  (An earlier "strong gap = 61%" reading was a NULL-bucket artifact — 77 old trades
  with the metric never recorded falling through a CASE into the top band.)
- **ADX 25-30 is a genuine, MACD-independent dead zone.** 41-44% WR regardless of
  MACD strength; both neighbours (20-25 ≈ 53.5%, 30+ ≈ 55-60%) are profitable.

| Scenario | n | WR | P&L |
|---|---|---|---|
| Baseline (all flips) | 389 | 50.9% | **−$13.26** |
| Skip ADX 25-30 dead zone | 291 | **54.0%** | **+$15.66** |

- **The predictive reversal signal is the gap *expanding*, not its level.** The
  level is flat as a predictor; the gap *grows* after a real flip and stays flat on
  a fake-out. That delta (`gap_now − gap_at_flip`) was never captured, so it can't
  be backtested from the store — only instrumented going forward.

## Changes

### `strategy/flip_strategy.py`
- New `FlipParams` fields (all default to legacy/off): `flip_confirm_bars=1`,
  `flip_gap_expansion_min=0.0`, `flip_adx_dead_lo=0.0`, `flip_adx_dead_hi=0.0`.
- Compute `gap_at_flip` (MACD gap/ATR at index `-bars_in_trend`) and
  `gap_expansion = macd_gap_atr − gap_at_flip` live from the same df — no new data
  source needed. Both stamped on `FlipDecision.metrics`.
- Flip branch now, in order: skip the ADX dead zone → wait `flip_confirm_bars` →
  require gap expansion (if enabled) → ADX floor → enter. The old static
  `cont_macd_gap_min` check was removed from the flip path (it was the wrong tool
  and coupled flips to the continuation lever).

### `strategy/flip_levers.py`
- Four new keys added to `_LEVER_KEYS` and `_defaults()` (defaults = off), so they
  flow through `build_flip_params()` and are stamped on every `DecisionRow.flip_levers`.

### `data/flip_levers.json` (gitignored runtime state — live values)
- `flip_confirm_bars=3` (wait ~3s), `flip_window_bars=7` (so bars 3-7 still count
  as a flip), `flip_adx_dead_lo/hi=25/30` (validated), `flip_gap_expansion_min=0`
  (capture-only — tune once the new metrics accrue). `adx_flip_min` stays 15.

### `dashboard/web/js/components/history.js`
- Trade-detail modal now shows RSI, bars-since-flip, MACD gap/ATR (with the
  at-flip value), and gap-expansion (green/red) so each trade can be inspected as
  the levers are tuned.

### Tests
- `tests/test_flip_strategy.py`: gap metrics captured; `flip_confirm_bars` waits;
  dead-zone exclusion; gap-expansion gate.
- `tests/test_flip_levers.py`: new keys load + reach `FlipParams`; defaults legacy.

## Rollout / how to tune

1. Live now: dead-zone skip + 3-bar wait are active; gap-expansion is capture-only.
2. After ~50-100 flips accrue with `gap_at_flip`/`gap_expansion` recorded, run the
   same WR-by-band analysis on the *expansion* (not the level) and set
   `flip_gap_expansion_min` to the threshold that separates real reversals from
   fake-outs. Edit `data/flip_levers.json` — no restart.
