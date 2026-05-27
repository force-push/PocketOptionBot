"""Pydantic-based configuration for the PocketOption trading bot."""

from enum import StrEnum
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsError

_PROJECT_ROOT = Path(__file__).parent.parent


class TradeMode(StrEnum):
    DEMO = "DEMO"
    LIVE = "LIVE"


class BotSettings(BaseSettings):
    """All configuration loaded from .env or environment variables."""

    # ── CDP ──
    cdp_url: str = Field(default="http://localhost:9222", alias="CDP_URL")

    # ── Trading Mode ──
    # DEMO is the ONLY default. LIVE requires explicit confirmation.
    trade_mode: TradeMode = Field(default=TradeMode.DEMO, alias="TRADE_MODE")

    # ── Asset & Timing ──
    asset: str = Field(default="EURUSD", alias="ASSET")
    expiry_seconds: int = Field(default=60, alias="EXPIRY_SECONDS", gt=0)
    trade_amount: float = Field(default=1.0, alias="TRADE_AMOUNT", gt=0)

    # ── Signal Engine ──
    min_confluence_score: float = Field(
        default=0.75, alias="MIN_CONFLUENCE_SCORE", ge=0.0, le=1.0
    )
    max_trades_per_hour: int = Field(default=10, alias="MAX_TRADES_PER_HOUR", ge=1)
    max_daily_loss_usd: float = Field(default=20.0, alias="MAX_DAILY_LOSS_USD", ge=0)
    candle_interval_seconds: int = Field(default=60, alias="CANDLE_INTERVAL_SECONDS", ge=1)
    history_length: int = Field(default=100, alias="HISTORY_LENGTH", ge=10)
    cooldown_after_loss_seconds: int = Field(default=120, alias="COOLDOWN_AFTER_LOSS_SECONDS", ge=0)

    # ── Risk ──
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    max_open_trades: int = Field(default=1, alias="MAX_OPEN_TRADES", ge=1)
    min_balance_multiplier: float = Field(default=5.0, alias="MIN_BALANCE_MULTIPLIER", ge=1.0)

    @field_validator("trade_mode", mode="before")
    @classmethod
    def _force_demo_if_unset(cls, v):
        if v is None:
            return TradeMode.DEMO
        mode = str(v).strip().upper()
        if mode not in (TradeMode.DEMO, TradeMode.LIVE):
            raise SettingsError(f"Invalid TRADE_MODE: {v!r}. Must be DEMO or LIVE.")
        return TradeMode(mode)

    class Config:
        env_file = _PROJECT_ROOT / ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Allow extra env vars without error

    def __init__(self, **data):
        super().__init__(**data)
        # Extra safety: hard-reset to DEMO if the env var is missing or empty.
        if "trade_mode" not in data:
            object.__setattr__(self, "trade_mode", TradeMode.DEMO)


# Global singleton for convenience (import once)
settings = BotSettings()