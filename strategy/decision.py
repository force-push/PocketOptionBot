"""Pure trade decision: require our TA to agree with the bot, combine into P(win).

Phase 1 keeps the combiner simple (mean of bot win-rate and our confluence) and
LOGS the components so Phase 3 can calibrate a better model from real outcomes.
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
    our_score_floor: float,
) -> Decision:
    if our_direction is None:
        return Decision(False, 0.0, "no_direction")
    if our_direction != bot_direction:
        return Decision(False, 0.0, "ta_disagree")
    if our_confluence < our_score_floor:
        return Decision(False, (bot_win_rate + our_confluence) / 2.0, "ta_low_score")
    combined = (bot_win_rate + our_confluence) / 2.0
    return Decision(True, combined, None)
