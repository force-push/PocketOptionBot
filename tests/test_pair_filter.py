"""Tests for the shared pair-eligibility filter."""
from __future__ import annotations

from types import SimpleNamespace

from strategy import pair_filter
from strategy.pair_filter import is_pair_allowed


def _cfg(regex="", allowed=None, blocked=None):
    return SimpleNamespace(
        allowed_pair_regex=regex,
        allowed_pairs=allowed or [],
        blocked_pairs=blocked or [],
    )


def test_regex_allows_matching_symbols():
    cfg = _cfg(regex="(USD|CNY|CNH|EUR)")
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert is_pair_allowed("JODCNY_otc", cfg)
    assert is_pair_allowed("EURNZD_otc", cfg)
    assert is_pair_allowed("USDCNH_otc", cfg)
    assert not is_pair_allowed("CADJPY_otc", cfg)   # no USD/CNY/CNH/EUR token


def test_regex_gbp_lookahead_excludes_all_gbp_crosses():
    cfg = _cfg(regex="^(?!.*GBP).*(USD|CNY|CNH|EUR)")
    assert is_pair_allowed("EURUSD_otc", cfg)
    assert is_pair_allowed("AUDUSD_otc", cfg)
    # GBP crosses are excluded even though they contain USD/EUR
    assert not is_pair_allowed("GBPUSD_otc", cfg)
    assert not is_pair_allowed("EURGBP_otc", cfg)
    assert not is_pair_allowed("GBPAUD_otc", cfg)


def test_regex_still_honours_blocklist():
    cfg = _cfg(regex="(USD)", blocked=["USDARS_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("USDARS_otc", cfg)


def test_exact_allowlist_when_no_regex():
    cfg = _cfg(allowed=["AUDUSD_otc", "EURNZD_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("EURUSD_otc", cfg)


def test_blocklist_only_when_no_allowlist():
    cfg = _cfg(blocked=["USDARS_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("USDARS_otc", cfg)


def test_bad_regex_falls_through_to_allowlist(monkeypatch):
    # An invalid pattern must not raise — it degrades to "no regex".
    pair_filter._compiled.clear()
    cfg = _cfg(regex="(unclosed", allowed=["AUDUSD_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("EURUSD_otc", cfg)


def test_empty_symbol_rejected():
    assert not is_pair_allowed("", _cfg(regex="(USD)"))
