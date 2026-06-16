"""Tests for the WR-optimizer logic in tools/analyze_failures.py."""
from __future__ import annotations

import importlib

af = importlib.import_module("tools.analyze_failures")


def _rows(bbw, outcome, n, dir_="CALL", pair="EURUSD_otc"):
    return [{"outcome": outcome, "bbw": bbw, "dir": dir_, "pair_api": pair,
             "kind": "flip", "adx": 30, "dist": 1.5, "gapstd": 0.1} for _ in range(n)]


def test_wr_and_band_stats():
    rows = _rows(10, "win", 6) + _rows(10, "loss", 4)
    w, n, _ = af._band_stats(rows, "bbw", 8, 14)
    assert n == 10 and w == 60.0
    # outside the band → not counted
    assert af._band_stats(rows, "bbw", 14, 18)[1] == 0


def test_recommend_loosen_excluded_winner(monkeypatch, capsys):
    # Gate excludes <8; a fat, clearly-winning 4-6 band should trigger LOOSEN.
    monkeypatch.setattr(af, "_active_levers", lambda: {"bb_width_min": 8, "bb_width_max": 18})
    rows = _rows(5.0, "win", 28) + _rows(5.0, "loss", 4)   # 4-6 band, ~88% WR, n=32
    af._recommend(rows)
    out = capsys.readouterr().out
    assert "LOOSEN" in out and "4-6" in out


def test_recommend_tighten_included_loser(monkeypatch, capsys):
    # Gate includes 8-14; a fat, clearly-losing 8-14 band should trigger TIGHTEN.
    monkeypatch.setattr(af, "_active_levers", lambda: {"bb_width_min": 8, "bb_width_max": 18})
    rows = _rows(10.0, "loss", 28) + _rows(10.0, "win", 4)   # 8-14 band, ~12% WR, n=32
    af._recommend(rows)
    out = capsys.readouterr().out
    assert "TIGHTEN" in out and "8-14" in out


def test_recommend_holds_on_thin_sample(monkeypatch, capsys):
    monkeypatch.setattr(af, "_active_levers", lambda: {"bb_width_min": 8, "bb_width_max": 18})
    rows = _rows(5.0, "win", 10)   # profitable but n < MIN_ACT_N
    af._recommend(rows)
    out = capsys.readouterr().out
    assert "no high-confidence lever change" in out


def test_recommend_holds_near_breakeven(monkeypatch, capsys):
    # n is large but WR sits right at break-even (inside the margin) → hold.
    monkeypatch.setattr(af, "_active_levers", lambda: {"bb_width_min": 8, "bb_width_max": 18})
    rows = _rows(5.0, "win", 26) + _rows(5.0, "loss", 24)   # 52% WR, within MARGIN
    af._recommend(rows)
    out = capsys.readouterr().out
    assert "no high-confidence lever change" in out
