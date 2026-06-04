"""Tests for telegram_feed/parser.py — all offline, no network."""

from __future__ import annotations

import pytest
from telegram_feed.parser import parse_signal, TelegramSignal


# ── Helper ────────────────────────────────────────────────────────────────────

def sig(text: str) -> TelegramSignal:
    """Parse and assert non-None."""
    result = parse_signal(text)
    assert result is not None, f"Expected signal from: {text!r}"
    return result


# ── Format 1: standard "PAIR CALL/PUT M1 Win rate: X%" ──────────────────────

def test_format_eurusd_otc_call():
    s = sig("EUR/USD OTC CALL M1 Win rate: 87%")
    assert s.pair == "EURUSD_otc"
    assert s.direction == "CALL"
    assert s.expiry_seconds == 60
    assert s.stated_win_rate == pytest.approx(0.87)


def test_format_eurusd_otc_put():
    s = sig("EUR/USD OTC PUT M5 Win rate: 92%")
    assert s.pair == "EURUSD_otc"
    assert s.direction == "PUT"
    assert s.expiry_seconds == 300
    assert s.stated_win_rate == pytest.approx(0.92)


# ── Format 2: BUY/SELL direction aliases ─────────────────────────────────────

def test_format_buy_alias():
    s = sig("EURUSD BUY 1 min Win rate: 80%")
    assert s.pair == "EURUSD"
    assert s.direction == "CALL"
    assert s.expiry_seconds == 60


def test_format_sell_alias():
    s = sig("GBP/USD SELL 5 min Win rate: 75%")
    assert s.pair == "GBPUSD"
    assert s.direction == "PUT"
    assert s.expiry_seconds == 300


# ── Format 3: UP/DOWN direction aliases ──────────────────────────────────────

def test_format_up_down():
    s = sig("EUR/USD OTC UP M1 WR 85%")
    assert s.pair == "EURUSD_otc"
    assert s.direction == "CALL"

    s2 = sig("EUR/USD OTC DOWN M1 WR 85%")
    assert s2.direction == "PUT"


# ── Format 4: arrow direction ────────────────────────────────────────────────

def test_format_arrow_up():
    s = sig("EURUSD OTC ↑ M1 Win rate: 90%")
    assert s.direction == "CALL"


def test_format_arrow_down():
    s = sig("EURUSD OTC ↓ M5 Win rate: 88%")
    assert s.direction == "PUT"


# ── Format 5: expiry variants ─────────────────────────────────────────────────

def test_expiry_seconds():
    s = sig("EUR/USD CALL expiry 60s Win rate: 80%")
    assert s.expiry_seconds == 60


def test_expiry_seconds_shorthand():
    s = sig("EUR/USD CALL 120sec Win rate: 82%")
    assert s.expiry_seconds == 120


def test_expiry_minutes_spelled_out():
    s = sig("EUR/USD CALL 5 minutes Win rate: 85%")
    assert s.expiry_seconds == 300


def test_expiry_m15():
    s = sig("EUR/USD OTC PUT M15 Win rate: 78%")
    assert s.expiry_seconds == 900


# ── Format 6: no win rate ────────────────────────────────────────────────────

def test_no_win_rate():
    s = sig("EUR/USD OTC CALL M1")
    assert s.stated_win_rate is None
    assert s.direction == "CALL"


# ── Pair normalization ────────────────────────────────────────────────────────

def test_pair_normalization_slash_otc():
    s = sig("EUR/USD OTC CALL M1")
    assert s.pair == "EURUSD_otc"


def test_pair_normalization_no_slash():
    s = sig("EURUSD CALL M1")
    assert s.pair == "EURUSD"


def test_pair_normalization_gbpusd():
    s = sig("GBP/USD CALL M5 Win rate: 83%")
    assert s.pair == "GBPUSD"


def test_pair_normalization_gbpusd_otc():
    s = sig("GBP/USD OTC PUT M1 Win rate: 91%")
    assert s.pair == "GBPUSD_otc"


def test_pair_normalization_usdjpy():
    s = sig("USD/JPY OTC CALL M1 Win rate: 79%")
    assert s.pair == "USDJPY_otc"


# ── Garbage / unparseable messages ───────────────────────────────────────────

def test_garbage_returns_none():
    assert parse_signal("Hello, how are you?") is None


def test_empty_string_returns_none():
    assert parse_signal("") is None


def test_none_input_returns_none():
    assert parse_signal(None) is None  # type: ignore[arg-type]


def test_only_pair_no_direction_returns_none():
    # No direction keyword — should fail direction extraction
    assert parse_signal("EUR/USD OTC M1") is None


def test_random_numbers_returns_none():
    assert parse_signal("1234 5678 9012") is None


def test_partial_message_no_pair():
    # Direction present but no recognizable pair
    assert parse_signal("CALL M1 Win rate: 90%") is None


# ── Frozen dataclass ─────────────────────────────────────────────────────────

def test_telegram_signal_is_frozen():
    s = sig("EUR/USD OTC CALL M1 Win rate: 87%")
    with pytest.raises((AttributeError, TypeError)):
        s.direction = "PUT"  # type: ignore[misc]


# ── Win rate edge cases ───────────────────────────────────────────────────────

def test_win_rate_100_percent():
    s = sig("EUR/USD CALL M1 Win rate: 100%")
    assert s.stated_win_rate == pytest.approx(1.0)


def test_win_rate_decimal_label():
    s = sig("EUR/USD CALL M1 win rate 0.87")
    assert s.stated_win_rate == pytest.approx(0.87)
