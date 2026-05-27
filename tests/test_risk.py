"""Test risk manager constraints."""

import pytest
from datetime import datetime, timedelta
from strategy.risk import RiskManager


def test_max_balance_check():
    """Min balance check should block if insufficient."""
    rm = RiskManager(
        max_trades_per_hour=10,
        max_daily_loss_usd=20.0,
        cooldown_after_loss_seconds=120,
        trade_amount=1.0,
        min_balance_multiplier=5.0,
    )

    # Balance too low
    assert rm.is_allowed(current_balance=3.0) is False
    assert "Balance too low" in rm.block_reason

    # Balance sufficient
    assert rm.is_allowed(current_balance=5.0) is True


def test_max_trades_per_hour():
    """Should block after max trades/hour."""
    rm = RiskManager(
        max_trades_per_hour=2,
        max_daily_loss_usd=20.0,
        cooldown_after_loss_seconds=120,
        trade_amount=1.0,
        min_balance_multiplier=5.0,
    )

    # Place 2 trades
    rm.record_trade("CALL", 1.0, "WIN")
    rm.record_trade("PUT", 1.0, "WIN")

    # 3rd trade should be blocked
    assert rm.is_allowed(current_balance=100.0) is False
    assert "Max trades/hour" in rm.block_reason


def test_cooldown_after_loss():
    """Should block for cooldown period after loss."""
    rm = RiskManager(
        max_trades_per_hour=100,
        max_daily_loss_usd=20.0,
        cooldown_after_loss_seconds=60,
        trade_amount=1.0,
        min_balance_multiplier=5.0,
    )

    # Record a loss
    rm.record_trade("CALL", 1.0, "LOSS")

    # Immediate next trade should be blocked
    assert rm.is_allowed(current_balance=100.0) is False
    assert "Cooling down" in rm.block_reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
