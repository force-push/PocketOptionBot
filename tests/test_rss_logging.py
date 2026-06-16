"""Test the peak-RSS memory instrumentation (Tier 5)."""
from __future__ import annotations

import main_v2


def test_peak_rss_mb_is_positive():
    mb = main_v2._peak_rss_mb()
    assert isinstance(mb, float)
    assert mb > 0          # the test process itself has a non-zero RSS


def test_log_rss_only_fires_on_interval(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(main_v2, "_RSS_LOG_EVERY", 50)
    monkeypatch.setattr(main_v2, "_peak_rss_mb", lambda: calls.append(1) or 123.0)

    main_v2._log_rss(0)     # cycle 0 → skip
    main_v2._log_rss(49)    # not a multiple → skip
    main_v2._log_rss(50)    # fires
    main_v2._log_rss(100)   # fires
    assert len(calls) == 2


def test_log_rss_never_raises(monkeypatch):
    def _boom():
        raise RuntimeError("rusage unavailable")
    monkeypatch.setattr(main_v2, "_peak_rss_mb", _boom)
    monkeypatch.setattr(main_v2, "_RSS_LOG_EVERY", 1)
    main_v2._log_rss(1)     # must swallow the error
