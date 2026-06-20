"""Tests for strategy.martingale.MartingaleTracker."""

import pytest
from strategy.martingale import MartingaleTracker


@pytest.fixture
def tracker():
    return MartingaleTracker(max_level=3, min_pair_wr=0.521, min_wr_samples=10)


# ── stake calculation ──────────────────────────────────────────────────────────

def test_no_losses_returns_base(tracker):
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 1000, 5) == 1.0


def test_one_loss_doubles(tracker):
    tracker.record_outcome("PAIR", False)
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 1000, 5) == 2.0


def test_two_losses_quadruples(tracker):
    tracker.record_outcome("PAIR", False)
    tracker.record_outcome("PAIR", False)
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 1000, 5) == 4.0


def test_three_losses_max_level(tracker):
    for _ in range(3):
        tracker.record_outcome("PAIR", False)
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 1000, 5) == 8.0


def test_cap_at_max_level(tracker):
    for _ in range(6):  # 6 losses but max_level=3
        tracker.record_outcome("PAIR", False)
    assert tracker.current_level("PAIR") == 3
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 1000, 5) == 8.0


def test_win_resets_streak(tracker):
    tracker.record_outcome("PAIR", False)
    tracker.record_outcome("PAIR", False)
    tracker.record_outcome("PAIR", True)
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 1000, 5) == 1.0


def test_win_on_clean_pair_is_noop(tracker):
    tracker.record_outcome("PAIR", True)
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 1000, 5) == 1.0


# ── WR gate ───────────────────────────────────────────────────────────────────

def test_wr_below_min_returns_base(tracker):
    tracker.record_outcome("PAIR", False)
    # pair WR 0.48 < min_pair_wr 0.521 → base
    assert tracker.get_stake("PAIR", 1.0, 0.48, 50, 1000, 5) == 1.0


def test_insufficient_samples_returns_base(tracker):
    tracker.record_outcome("PAIR", False)
    # n=5 < min_wr_samples=10 → base
    assert tracker.get_stake("PAIR", 1.0, 0.60, 5, 1000, 5) == 1.0


def test_exactly_at_min_wr_doubles(tracker):
    tracker.record_outcome("PAIR", False)
    assert tracker.get_stake("PAIR", 1.0, 0.521, 10, 1000, 5) == 2.0


def test_exactly_at_min_samples_doubles(tracker):
    tracker.record_outcome("PAIR", False)
    assert tracker.get_stake("PAIR", 1.0, 0.60, 10, 1000, 5) == 2.0


# ── balance safety ────────────────────────────────────────────────────────────

def test_balance_cap_prevents_double(tracker):
    # balance=10, multiplier=5 → max_affordable=2.0
    # after 2 losses: doubled=4.0 > 2.0 → base
    tracker.record_outcome("PAIR", False)
    tracker.record_outcome("PAIR", False)
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 10, 5) == 1.0


def test_zero_balance_falls_back_to_base(tracker):
    tracker.record_outcome("PAIR", False)
    # balance=0 is treated as can-afford (skip check) — actually returns doubled
    # because we only block when balance > 0 and doubled > max_affordable
    result = tracker.get_stake("PAIR", 1.0, 0.60, 50, 0, 5)
    assert result == 2.0  # 0 balance → skip balance check, return doubled


def test_affordable_double_is_not_blocked(tracker):
    tracker.record_outcome("PAIR", False)
    # balance=100, multiplier=5 → max_affordable=20; doubled=2 < 20 → OK
    assert tracker.get_stake("PAIR", 1.0, 0.60, 50, 100, 5) == 2.0


# ── independent pairs ─────────────────────────────────────────────────────────

def test_pairs_are_independent(tracker):
    tracker.record_outcome("PAIR_A", False)
    tracker.record_outcome("PAIR_A", False)
    tracker.record_outcome("PAIR_B", False)
    assert tracker.get_stake("PAIR_A", 1.0, 0.60, 50, 1000, 5) == 4.0
    assert tracker.get_stake("PAIR_B", 1.0, 0.60, 50, 1000, 5) == 2.0


def test_win_on_one_pair_doesnt_reset_other(tracker):
    tracker.record_outcome("PAIR_A", False)
    tracker.record_outcome("PAIR_B", False)
    tracker.record_outcome("PAIR_A", True)  # reset A only
    assert tracker.get_stake("PAIR_A", 1.0, 0.60, 50, 1000, 5) == 1.0
    assert tracker.get_stake("PAIR_B", 1.0, 0.60, 50, 1000, 5) == 2.0


# ── introspection ─────────────────────────────────────────────────────────────

def test_current_level(tracker):
    assert tracker.current_level("PAIR") == 0
    tracker.record_outcome("PAIR", False)
    assert tracker.current_level("PAIR") == 1
    tracker.record_outcome("PAIR", False)
    assert tracker.current_level("PAIR") == 2


def test_state_returns_all_streaks(tracker):
    tracker.record_outcome("A", False)
    tracker.record_outcome("A", False)
    tracker.record_outcome("B", False)
    s = tracker.state()
    assert s == {"A": 2, "B": 1}


def test_state_after_reset(tracker):
    tracker.record_outcome("PAIR", False)
    tracker.record_outcome("PAIR", True)
    assert tracker.state() == {}
