"""Pure trade decision for the signals loop (Telegram/broker_bot mode removed 2026-06-12)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    trade: bool
    combined_probability: float
    skip_reason: str | None


def decide_signals(
    our_direction: str | None,
    our_confluence: float,
    tracked_win_rate: float = 0.5,
) -> Decision:
    """Signals mode: direction from TA confluence only, no broker-bot input.

    MACD+EMA gate is enforced upstream by the ConfluenceEngine (decision_signals).
    A non-None direction means the gate passed. P(win) uses the tracked per-pair
    win-rate so the EV gate downstream has a calibrated probability to work with.
    """
    if our_direction is None:
        return Decision(False, 0.0, "no_direction")
    combined = (tracked_win_rate + our_confluence) / 2.0
    return Decision(True, combined, None)
