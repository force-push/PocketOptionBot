"""Tests for strategy.martingale.MartingaleTracker."""

import pytest
from strategy.martingale import MartingaleTracker

# Default call-time params matching .env defaults; min_session_trades=0 disables
# the session gate so pre-existing tests remain unaffected by the new gate.
_DEFAULTS = dict(multiplier=2.0, max_level=2, min_pair_wr=0.521, min_wr_samples=10, min_session_trades=0)
# Subset for record_outcome (only takes max_level + multiplier)
_RO = dict(max_level=2, multiplier=2.0)


@pytest.fixture
def tracker():
    return MartingaleTracker()


def _stake(t, pair, base=1.0, wr=0.60, n=50, bal=1000, mult=5, **kw):
    """Helper: call get_stake with sensible defaults."""
    params = {**_DEFAULTS, **kw}
    return t.get_stake(pair, base, wr, n, bal, mult, **params)


# ── stake calculation ──────────────────────────────────────────────────────────

def test_no_losses_returns_base(tracker):
    assert _stake(tracker, "PAIR") == 1.0


def test_one_loss_doubles(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    assert _stake(tracker, "PAIR") == 2.0


def test_two_losses_quadruples(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    tracker.record_outcome("PAIR", False, **_RO)
    assert _stake(tracker, "PAIR") == 4.0


def test_cap_at_max_level(tracker):
    for _ in range(5):  # 5 losses but max_level=2
        tracker.record_outcome("PAIR", False, **_RO)
    assert tracker.current_level("PAIR", max_level=2) == 2
    assert _stake(tracker, "PAIR") == 4.0


def test_win_resets_streak(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    tracker.record_outcome("PAIR", False, **_RO)
    tracker.record_outcome("PAIR", True, **_RO)
    assert _stake(tracker, "PAIR") == 1.0


def test_win_on_clean_pair_is_noop(tracker):
    tracker.record_outcome("PAIR", True, **_RO)
    assert _stake(tracker, "PAIR") == 1.0


# ── custom multiplier ─────────────────────────────────────────────────────────

def test_custom_multiplier_2_2(tracker):
    tracker.record_outcome("PAIR", False, multiplier=2.2, max_level=2)
    result = _stake(tracker, "PAIR", multiplier=2.2, max_level=2)
    assert abs(result - 2.2) < 1e-9


def test_custom_multiplier_two_losses(tracker):
    tracker.record_outcome("PAIR", False, multiplier=2.2, max_level=2)
    tracker.record_outcome("PAIR", False, multiplier=2.2, max_level=2)
    result = _stake(tracker, "PAIR", multiplier=2.2, max_level=2)
    assert abs(result - 2.2 ** 2) < 1e-9  # 4.84


def test_max_level_3(tracker):
    for _ in range(4):
        tracker.record_outcome("PAIR", False, multiplier=2.0, max_level=3)
    assert _stake(tracker, "PAIR", multiplier=2.0, max_level=3) == 8.0  # 2^3


# ── WR gate ───────────────────────────────────────────────────────────────────

def test_wr_below_min_returns_base(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    # WR 0.48 < 0.521 → base
    assert _stake(tracker, "PAIR", wr=0.48) == 1.0


def test_insufficient_samples_returns_base(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    # n=5 < min_wr_samples=10 → base
    assert _stake(tracker, "PAIR", n=5) == 1.0


def test_exactly_at_min_wr_scales(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    assert _stake(tracker, "PAIR", wr=0.521) == 2.0


def test_exactly_at_min_samples_scales(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    assert _stake(tracker, "PAIR", n=10) == 2.0


# ── balance safety ────────────────────────────────────────────────────────────

def test_balance_cap_prevents_scale(tracker):
    # balance=10, mult=5 → max_affordable=2.0; after 2 losses: 4.0 > 2.0 → base
    tracker.record_outcome("PAIR", False, **_RO)
    tracker.record_outcome("PAIR", False, **_RO)
    assert _stake(tracker, "PAIR", bal=10, mult=5) == 1.0


def test_zero_balance_skips_cap(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    # balance=0 → skip balance check → return scaled
    assert _stake(tracker, "PAIR", bal=0) == 2.0


def test_affordable_scale_not_blocked(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    # balance=100, mult=5 → max_affordable=20; 2.0 < 20 → OK
    assert _stake(tracker, "PAIR", bal=100, mult=5) == 2.0


# ── independent pairs ─────────────────────────────────────────────────────────

def test_pairs_are_independent(tracker):
    tracker.record_outcome("A", False, **_RO)
    tracker.record_outcome("A", False, **_RO)
    tracker.record_outcome("B", False, **_RO)
    assert _stake(tracker, "A") == 4.0
    assert _stake(tracker, "B") == 2.0


def test_win_on_one_pair_doesnt_reset_other(tracker):
    tracker.record_outcome("A", False, **_RO)
    tracker.record_outcome("B", False, **_RO)
    tracker.record_outcome("A", True, **_RO)
    assert _stake(tracker, "A") == 1.0
    assert _stake(tracker, "B") == 2.0


# ── introspection ─────────────────────────────────────────────────────────────

def test_current_level(tracker):
    assert tracker.current_level("PAIR", max_level=2) == 0
    tracker.record_outcome("PAIR", False, **_RO)
    assert tracker.current_level("PAIR", max_level=2) == 1
    tracker.record_outcome("PAIR", False, **_RO)
    assert tracker.current_level("PAIR", max_level=2) == 2


def test_state_returns_all_streaks(tracker):
    tracker.record_outcome("A", False, **_RO)
    tracker.record_outcome("A", False, **_RO)
    tracker.record_outcome("B", False, **_RO)
    assert tracker.state() == {"A": 2, "B": 1}


def test_state_after_reset(tracker):
    tracker.record_outcome("PAIR", False, **_RO)
    tracker.record_outcome("PAIR", True, **_RO)
    assert tracker.state() == {}


# ── session trades gate ───────────────────────────────────────────────────────

def _stake_sess(t, pair, base=1.0, wr=0.60, n=50, bal=1000, mult=5, **kw):
    """Helper with session gate enabled (min_session_trades=3)."""
    params = {**_DEFAULTS, "min_session_trades": 3, **kw}
    return t.get_stake(pair, base, wr, n, bal, mult, **params)


def test_session_gate_blocks_before_threshold(tracker):
    # 2 resolved trades on PAIR but min=3 — should return base
    tracker.record_outcome("PAIR", False, **_RO)
    tracker.record_outcome("PAIR", True, **_RO)
    assert _stake_sess(tracker, "PAIR") == 1.0


def test_session_gate_allows_at_threshold(tracker):
    # 3 resolved trades + a loss streak → should scale
    tracker.record_outcome("PAIR", True, **_RO)
    tracker.record_outcome("PAIR", True, **_RO)
    tracker.record_outcome("PAIR", False, **_RO)  # 3rd trade, also a loss → streak=1
    assert _stake_sess(tracker, "PAIR", min_pair_wr=0.0) == 2.0


def test_session_gate_zero_disables(tracker):
    # min_session_trades=0 means always allowed (backward compat)
    tracker.record_outcome("PAIR", False, **_RO)  # only 1 trade
    result = _stake_sess(tracker, "PAIR", min_session_trades=0, min_pair_wr=0.0)
    assert result == 2.0


def test_session_trades_count_wins_and_losses(tracker):
    # Wins count toward session total even though they reset the streak
    tracker.record_outcome("PAIR", True, **_RO)
    tracker.record_outcome("PAIR", True, **_RO)
    tracker.record_outcome("PAIR", False, **_RO)  # 3 total, streak=1
    assert _stake_sess(tracker, "PAIR", min_pair_wr=0.0) == 2.0


def test_session_gate_independent_per_pair(tracker):
    # Pair A has 3 session trades, Pair B has 1 — only A should double
    tracker.record_outcome("A", True, **_RO)
    tracker.record_outcome("A", True, **_RO)
    tracker.record_outcome("A", False, **_RO)  # streak=1
    tracker.record_outcome("B", False, **_RO)  # only 1 session trade
    assert _stake_sess(tracker, "A", min_pair_wr=0.0) == 2.0
    assert _stake_sess(tracker, "B", min_pair_wr=0.0) == 1.0
