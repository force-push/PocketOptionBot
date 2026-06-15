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
