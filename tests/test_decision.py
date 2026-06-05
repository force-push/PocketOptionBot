from strategy.decision import decide, Decision

def test_agreement_trade():
    d = decide(bot_direction="CALL", our_direction="CALL",
               bot_win_rate=0.78, our_confluence=0.80)
    assert isinstance(d, Decision)
    assert d.trade is True
    assert d.skip_reason is None
    assert abs(d.combined_probability - 0.79) < 1e-9

def test_disagreement_skips():
    d = decide(bot_direction="CALL", our_direction="PUT",
               bot_win_rate=0.78, our_confluence=0.80)
    assert d.trade is False
    assert d.skip_reason == "ta_disagree"

def test_no_our_direction_skips():
    d = decide(bot_direction="CALL", our_direction=None,
               bot_win_rate=0.78, our_confluence=0.0)
    assert d.trade is False
    assert d.skip_reason == "no_direction"
