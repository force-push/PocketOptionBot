"""Tests for strategy/win_rate.py — all offline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from strategy.win_rate import WinRateTracker


@pytest.fixture
def tmp_tracker(tmp_path):
    """Create a WinRateTracker backed by a temporary JSON file."""
    return WinRateTracker(json_path=tmp_path / "win_rates.json")


# ── Basic record and rate ─────────────────────────────────────────────────────

def test_initial_rate_is_zero(tmp_tracker):
    rate, n = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    assert rate == 0.0
    assert n == 0


def test_record_win(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    rate, n = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    assert rate == pytest.approx(1.0)
    assert n == 1


def test_record_loss(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "loss")
    rate, n = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    assert rate == pytest.approx(0.0)
    assert n == 1


def test_pair_rate_aggregates_across_keys(tmp_tracker):
    # Different directions and expiries for the same pair should aggregate.
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    tmp_tracker.record("EURUSD_otc", "PUT", 300, "loss")   # different dir + expiry bucket
    rate, n = tmp_tracker.pair_rate("EURUSD_otc")
    assert n == 3
    assert rate == pytest.approx(2 / 3)
    # A pair with no history → (0, 0)
    assert tmp_tracker.pair_rate("GBPUSD_otc") == (0.0, 0)


def test_mixed_outcomes(tmp_tracker):
    for _ in range(7):
        tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    for _ in range(3):
        tmp_tracker.record("EURUSD_otc", "CALL", 60, "loss")
    rate, n = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    assert rate == pytest.approx(0.7)
    assert n == 10


def test_draw_does_not_count(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "draw")
    rate, n = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    # Draw not counted — n should be 1
    assert n == 1
    assert rate == pytest.approx(1.0)


# ── Keys are independent ──────────────────────────────────────────────────────

def test_different_pairs_are_independent(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    tmp_tracker.record("GBPUSD_otc", "CALL", 60, "loss")
    r1, n1 = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    r2, n2 = tmp_tracker.rate("GBPUSD_otc", "CALL", 60)
    assert r1 == pytest.approx(1.0) and n1 == 1
    assert r2 == pytest.approx(0.0) and n2 == 1


def test_direction_separates_keys(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    tmp_tracker.record("EURUSD_otc", "PUT", 60, "loss")
    r_call, _ = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    r_put, _ = tmp_tracker.rate("EURUSD_otc", "PUT", 60)
    assert r_call == pytest.approx(1.0)
    assert r_put == pytest.approx(0.0)


def test_expiry_bucket_separates_keys(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")   # 1m bucket
    tmp_tracker.record("EURUSD_otc", "CALL", 300, "loss")  # 5m bucket
    r1, _ = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    r2, _ = tmp_tracker.rate("EURUSD_otc", "CALL", 300)
    assert r1 == pytest.approx(1.0)
    assert r2 == pytest.approx(0.0)


# ── Cold start ────────────────────────────────────────────────────────────────

def test_cold_start_passes_below_min_samples(tmp_tracker):
    """Gate should return True when n < min_samples."""
    # Only 3 records, min_samples=20
    for _ in range(3):
        tmp_tracker.record("EURUSD_otc", "CALL", 60, "loss")
    assert tmp_tracker.passes("EURUSD_otc", "CALL", 60, 0.55, 20) is True


def test_gate_fails_after_warmup(tmp_tracker):
    """After enough samples and poor rate, gate should fail."""
    # 20 losses → 0% win rate
    for _ in range(20):
        tmp_tracker.record("EURUSD_otc", "CALL", 60, "loss")
    assert tmp_tracker.passes("EURUSD_otc", "CALL", 60, 0.55, 20) is False


def test_gate_passes_after_warmup_good_rate(tmp_tracker):
    for _ in range(15):
        tmp_tracker.record("EURUSD_otc", "CALL", 60, "win")
    for _ in range(5):
        tmp_tracker.record("EURUSD_otc", "CALL", 60, "loss")
    # 75% win rate ≥ 0.55
    assert tmp_tracker.passes("EURUSD_otc", "CALL", 60, 0.55, 20) is True


def test_cold_start_zero_samples(tmp_tracker):
    """No records at all → cold-start pass."""
    assert tmp_tracker.passes("EURUSD_otc", "CALL", 60, 0.55, 20) is True


# ── Persistence (round-trip) ──────────────────────────────────────────────────

def test_persistence_round_trip(tmp_path):
    json_path = tmp_path / "wr.json"
    t1 = WinRateTracker(json_path=json_path)
    for _ in range(7):
        t1.record("EURUSD_otc", "CALL", 60, "win")
    for _ in range(3):
        t1.record("EURUSD_otc", "CALL", 60, "loss")
    t1.save()

    # Load fresh tracker from same file
    t2 = WinRateTracker(json_path=json_path)
    rate, n = t2.rate("EURUSD_otc", "CALL", 60)
    assert n == 10
    assert rate == pytest.approx(0.7)


def test_persistence_file_created(tmp_path):
    json_path = tmp_path / "wr.json"
    t = WinRateTracker(json_path=json_path)
    t.record("EURUSD_otc", "CALL", 60, "win")
    assert json_path.exists()


def test_persistence_content_is_valid_json(tmp_path):
    json_path = tmp_path / "wr.json"
    t = WinRateTracker(json_path=json_path)
    t.record("EURUSD_otc", "CALL", 60, "win")
    with open(json_path) as f:
        data = json.load(f)
    assert isinstance(data, dict)


# ── Edge cases ────────────────────────────────────────────────────────────────

def test_unknown_outcome_ignored(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "unknown_value")
    _, n = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    assert n == 0


def test_outcome_case_insensitive(tmp_tracker):
    tmp_tracker.record("EURUSD_otc", "CALL", 60, "WIN")
    rate, n = tmp_tracker.rate("EURUSD_otc", "CALL", 60)
    assert rate == pytest.approx(1.0)
    assert n == 1
