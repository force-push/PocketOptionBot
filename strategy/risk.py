"""Risk manager: enforce trading limits and safeguards."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from utils.logger import log


@dataclass
class TradeRecord:
    timestamp: datetime
    direction: str
    amount: float
    result: str  # "WIN", "LOSS", "PENDING"


class RiskManager:
    """Enforce all risk constraints before allowing a trade."""

    def __init__(
        self,
        max_trades_per_hour: int,
        max_daily_loss_usd: float,
        cooldown_after_loss_seconds: int,
        trade_amount: float,
        min_balance_multiplier: float = 5.0,
    ):
        self.max_trades_per_hour = max_trades_per_hour
        self.max_daily_loss_usd = max_daily_loss_usd
        self.cooldown_after_loss_seconds = cooldown_after_loss_seconds
        self.trade_amount = trade_amount
        self.min_balance_multiplier = min_balance_multiplier

        self.trade_history: deque[TradeRecord] = deque()
        self.last_loss_time: datetime | None = None
        self.daily_pnl: float = 0.0

        self.block_reason: str = ""

    # ────────────────────────────────────────────────────────────────

    def is_allowed(self, current_balance: float | None = None) -> bool:
        """Check all constraints. Set self.block_reason if blocked."""
        self.block_reason = ""

        # Balance check
        if current_balance is not None:
            min_balance = self.trade_amount * self.min_balance_multiplier
            if current_balance < min_balance:
                self.block_reason = f"Balance too low: {current_balance:.2f} < {min_balance:.2f}"
                return False

        # Trades per hour
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        recent = [t for t in self.trade_history if t.timestamp > hour_ago]
        if len(recent) >= self.max_trades_per_hour:
            self.block_reason = f"Max trades/hour: {len(recent)} >= {self.max_trades_per_hour}"
            return False

        # Daily loss limit
        if self.daily_pnl < -self.max_daily_loss_usd:
            self.block_reason = f"Daily loss limit exceeded: {self.daily_pnl:.2f} <= -{self.max_daily_loss_usd:.2f}"
            return False

        # Cooldown after loss
        if self.last_loss_time is not None:
            elapsed = (now - self.last_loss_time).total_seconds()
            if elapsed < self.cooldown_after_loss_seconds:
                remaining = self.cooldown_after_loss_seconds - elapsed
                self.block_reason = f"Cooling down after loss: {remaining:.0f}s remaining"
                return False

        return True

    def record_trade(self, direction: str, amount: float, result: str) -> None:
        """Record a completed trade and update P&L."""
        now = datetime.now()
        self.trade_history.append(TradeRecord(now, direction, amount, result))

        if result == "WIN":
            self.daily_pnl += amount
        elif result == "LOSS":
            self.daily_pnl -= amount
            self.last_loss_time = now

        log.info(
            f"Trade recorded: {result} {direction} ${amount:.2f} | Daily P&L: {self.daily_pnl:+.2f}"
        )

    def reset_daily(self) -> None:
        """Reset daily P&L (call at market open)."""
        self.daily_pnl = 0.0
        log.info("Daily P&L reset")
