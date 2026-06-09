"""Tests for decide_signals() — signals-mode decision function (Option A)."""
from strategy.decision import decide_signals, Decision


def test_signals_mode_call_direction():
    d = decide_signals(our_direction="CALL", our_confluence=0.70, tracked_win_rate=0.60)
    assert isinstance(d, Decision)
    assert d.trade is True
    assert d.skip_reason is None
    assert abs(d.combined_probability - 0.65) < 1e-9


def test_signals_mode_put_direction():
    d = decide_signals(our_direction="PUT", our_confluence=0.55, tracked_win_rate=0.58)
    assert d.trade is True
    assert d.skip_reason is None


def test_signals_mode_no_direction_skips():
    d = decide_signals(our_direction=None, our_confluence=0.0)
    assert d.trade is False
    assert d.skip_reason == "no_direction"
    assert d.combined_probability == 0.0


def test_signals_mode_no_ta_disagree_concept():
    # In signals mode there is no bot direction to disagree with — any non-None
    # direction from the confluence gate is valid.
    d = decide_signals(our_direction="CALL", our_confluence=0.40)
    assert d.trade is True


def test_signals_mode_default_tracked_win_rate():
    # When no tracked history exists yet, tracked_win_rate defaults to 0.5
    d = decide_signals(our_direction="CALL", our_confluence=0.60)
    assert d.trade is True
    assert abs(d.combined_probability - 0.55) < 1e-9


def test_signals_mode_combined_probability_formula():
    # combined = (tracked_win_rate + our_confluence) / 2.0
    d = decide_signals(our_direction="CALL", our_confluence=0.80, tracked_win_rate=0.70)
    assert abs(d.combined_probability - 0.75) < 1e-9
