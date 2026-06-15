"""Tests for the live-tunable flip levers loader."""
from __future__ import annotations

import json

from strategy import flip_levers
from strategy.flip_levers import load_levers


def test_missing_file_returns_defaults(tmp_path):
    levers = load_levers(str(tmp_path / "nope.json"))
    # all known keys present, sourced from settings defaults
    for k in ("st_period", "adx_flip_min", "adx_max", "require_adx_rising"):
        assert k in levers


def test_file_overrides_defaults(tmp_path):
    p = tmp_path / "flip_levers.json"
    p.write_text(json.dumps({"adx_max": 40, "flip_window_bars": 5, "junk": 1}))
    flip_levers._cache["sig"] = None  # bypass cross-test cache
    levers = load_levers(str(p))
    assert levers["adx_max"] == 40
    assert levers["flip_window_bars"] == 5
    assert "junk" not in levers  # unknown keys ignored


def test_null_keys_fall_back(tmp_path):
    p = tmp_path / "flip_levers.json"
    p.write_text(json.dumps({"adx_max": None, "adx_flip_min": 30}))
    flip_levers._cache["sig"] = None
    levers = load_levers(str(p))
    assert levers["adx_flip_min"] == 30
    # null adx_max falls back to the settings default, not None
    assert levers["adx_max"] is not None


def test_bad_json_returns_defaults(tmp_path):
    p = tmp_path / "flip_levers.json"
    p.write_text("{not valid json")
    flip_levers._cache["sig"] = None
    levers = load_levers(str(p))
    assert "adx_max" in levers and levers["adx_max"] is not None


def test_flip_wait_confirm_levers_wired(tmp_path):
    """New flip wait-and-confirm keys load and reach FlipParams via build_flip_params."""
    p = tmp_path / "flip_levers.json"
    p.write_text(json.dumps({
        "flip_confirm_bars": 3, "flip_gap_expansion_min": 0.15,
        "flip_adx_dead_lo": 25, "flip_adx_dead_hi": 30,
    }))
    flip_levers._cache["sig"] = None
    levers = load_levers(str(p))
    assert levers["flip_confirm_bars"] == 3
    assert levers["flip_gap_expansion_min"] == 0.15
    assert levers["flip_adx_dead_lo"] == 25
    assert levers["flip_adx_dead_hi"] == 30
    # and they construct a FlipParams without error, carrying the values through
    params = flip_levers.build_flip_params(levers)
    assert params.flip_confirm_bars == 3
    assert params.flip_adx_dead_hi == 30


def test_flip_wait_confirm_defaults_are_legacy(tmp_path):
    """Absent file → wait-and-confirm disabled (enter at the turn, no dead zone)."""
    levers = load_levers(str(tmp_path / "nope.json"))
    assert levers["flip_confirm_bars"] == 1        # 1 = enter at the turn
    assert levers["flip_gap_expansion_min"] == 0.0  # off
    assert levers["flip_adx_dead_lo"] == 0.0        # off
    assert levers["flip_adx_dead_hi"] == 0.0
