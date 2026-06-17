"""Tests for the per-pair post-loss cooldown."""
from __future__ import annotations

from strategy.pair_cooldown import PairCooldown


def test_no_cooldown_before_any_loss():
    pc = PairCooldown(seconds=60)
    assert not pc.is_cooling("EURUSD_otc", now=100.0)


def test_cooling_within_window():
    pc = PairCooldown(seconds=60)
    pc.record_loss("EURUSD_otc", now=100.0)
    assert pc.is_cooling("EURUSD_otc", now=130.0)      # 30s later, still cooling
    assert pc.is_cooling("EURUSD_otc", now=159.9)


def test_not_cooling_after_window():
    pc = PairCooldown(seconds=60)
    pc.record_loss("EURUSD_otc", now=100.0)
    assert not pc.is_cooling("EURUSD_otc", now=160.0)   # exactly 60s → expired
    assert not pc.is_cooling("EURUSD_otc", now=200.0)


def test_zero_seconds_disables():
    pc = PairCooldown(seconds=0)
    pc.record_loss("EURUSD_otc", now=100.0)
    assert not pc.is_cooling("EURUSD_otc", now=100.0)


def test_only_affects_the_losing_pair():
    pc = PairCooldown(seconds=60)
    pc.record_loss("EURUSD_otc", now=100.0)
    assert pc.is_cooling("EURUSD_otc", now=120.0)
    assert not pc.is_cooling("AUDUSD_otc", now=120.0)


def test_cooling_set():
    pc = PairCooldown(seconds=60)
    pc.record_loss("EURUSD_otc", now=100.0)
    pc.record_loss("AUDUSD_otc", now=150.0)
    assert pc.cooling(now=160.0) == {"AUDUSD_otc"}    # EURUSD expired, AUDUSD live
    assert pc.cooling(now=120.0) == {"EURUSD_otc"}


def test_re_loss_resets_window():
    pc = PairCooldown(seconds=60)
    pc.record_loss("EURUSD_otc", now=100.0)
    pc.record_loss("EURUSD_otc", now=140.0)            # a second loss extends it
    assert pc.is_cooling("EURUSD_otc", now=199.0)      # 59s after the 2nd loss
    assert not pc.is_cooling("EURUSD_otc", now=200.0)


def test_empty_pair_is_noop():
    pc = PairCooldown(seconds=60)
    pc.record_loss("", now=100.0)
    assert not pc.is_cooling("", now=100.0)


# ── performance-based 12h cooldown ───────────────────────────────────────────
# In test mode (seconds provided) perf_cfg() returns: min=5, max_wr=0.40,
# window=3h, cooldown=12h.

def test_perf_no_trigger_before_min_trades():
    pc = PairCooldown(seconds=60)
    t = 1000.0
    for _ in range(2):   # 2 losses — one short of threshold (min=3)
        pc.record_outcome("EURHUF_otc", is_win=False, now=t)
        t += 10
    assert not pc.is_cooling("EURHUF_otc", now=t)   # perf gate not triggered yet


def test_perf_triggers_on_third_loss():
    pc = PairCooldown(seconds=60)
    t = 1000.0
    triggered = False
    for _ in range(3):
        triggered = pc.record_outcome("EURHUF_otc", is_win=False, now=t)
        t += 10
    assert triggered
    assert pc.is_cooling("EURHUF_otc", now=t)        # 12h cooldown active


def test_perf_no_trigger_above_wr_threshold():
    pc = PairCooldown(seconds=60)
    t = 1000.0
    # 3 wins, 2 losses → WR 60% > 40% threshold
    for is_win in [True, False, True, False, True]:
        pc.record_outcome("EURHUF_otc", is_win=is_win, now=t)
        t += 10
    assert not pc.is_cooling("EURHUF_otc", now=t)


def test_perf_cooldown_expires():
    pc = PairCooldown(seconds=60)
    t = 1000.0
    for _ in range(5):
        pc.record_outcome("EURHUF_otc", is_win=False, now=t)
        t += 10
    # 12h = 43200s; should be active at t and expired at t+43201
    assert pc.is_cooling("EURHUF_otc", now=t)
    assert not pc.is_cooling("EURHUF_otc", now=t + 43201)


def test_perf_cooldown_reason():
    pc = PairCooldown(seconds=60)
    t = 1000.0
    for _ in range(5):
        pc.record_outcome("PAIR_otc", is_win=False, now=t)
        t += 10
    reason = pc.cooling_reason("PAIR_otc", now=t)
    assert reason is not None and "perf-cooldown" in reason


def test_perf_window_prunes_old_outcomes():
    pc = PairCooldown(seconds=60)
    # 4 losses in the window, then they age out (3h = 10800s), then 1 fresh loss
    t = 1000.0
    for _ in range(4):
        pc.record_outcome("PAIR_otc", is_win=False, now=t)
        t += 10
    # Jump forward past the 3h window
    t += 11000
    triggered = pc.record_outcome("PAIR_otc", is_win=False, now=t)
    assert not triggered   # old 4 losses pruned; only 1 fresh loss in window


def test_perf_cooling_set_includes_perf_pairs():
    pc = PairCooldown(seconds=60)
    t = 1000.0
    for _ in range(5):
        pc.record_outcome("BAD_otc", is_win=False, now=t)
        t += 10
    assert "BAD_otc" in pc.cooling(now=t)
