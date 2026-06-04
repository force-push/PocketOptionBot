from strategy.expiry import select_expiry

ALLOWED = (5, 10, 15, 30, 60, 120, 300)

def test_defaults_to_configured_when_no_hint():
    assert select_expiry(default=30, allowed=ALLOWED) == 30

def test_snaps_requested_to_nearest_allowed():
    assert select_expiry(default=30, allowed=ALLOWED, requested=45) == 30  # nearest of 30/60 → 30
    assert select_expiry(default=30, allowed=ALLOWED, requested=12) == 10

def test_rejects_when_disallowed_and_no_default_match():
    assert select_expiry(default=60, allowed=ALLOWED, requested=99999) == 300  # nearest
