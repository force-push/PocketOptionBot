"""Pure trade decision: two modes — broker_bot (TA + bot agreement) and signals (TA only).

Phase 1 keeps the combiner simple (mean of win-rate and confluence) and LOGS
the components so Phase 3 can calibrate a better model from real outcomes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Decision:
    trade: bool
    combined_probability: float
    skip_reason: str | None


def decide(
    bot_direction: str,
    our_direction: str | None,
    bot_win_rate: float,
    our_confluence: float,
) -> Decision:
    """Broker-bot mode: require TA to agree with bot direction, combine win rates."""
    if our_direction is None:
        return Decision(False, 0.0, "no_direction")
    if our_direction != bot_direction:
        return Decision(False, 0.0, "ta_disagree")
    combined = (bot_win_rate + our_confluence) / 2.0
    return Decision(True, combined, None)


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
