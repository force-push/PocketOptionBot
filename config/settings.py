"""Pydantic-based configuration for the PocketOption trading bot."""

from enum import StrEnum
from pathlib import Path
from typing import Optional

from pydantic import ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsError

_PROJECT_ROOT = Path(__file__).parent.parent


class TradeMode(StrEnum):
    DEMO = "DEMO"
    LIVE = "LIVE"


class BotSettings(BaseSettings):
    """All configuration loaded from .env or environment variables."""

    # ── CDP (legacy — kept for backward compat, not in live path) ──
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

    # ── Telegram (Telethon user session) ──
    # Optional: module imports cleanly without a .env present.
    telegram_api_id: Optional[int] = Field(default=None, alias="TELEGRAM_API_ID")
    telegram_api_hash: Optional[str] = Field(default=None, alias="TELEGRAM_API_HASH")
    telegram_phone: Optional[str] = Field(default=None, alias="TELEGRAM_PHONE")
    telegram_session: str = Field(default="po_session", alias="TELEGRAM_SESSION")
    # StringSession string — preferred over file session in cloud/headless envs.
    # Generate with: python3 tools/gen_telegram_session.py
    telegram_session_string: Optional[str] = Field(default=None, alias="TELEGRAM_SESSION_STRING")
    signal_bot_username: str = Field(default="po_broker_bot", alias="SIGNAL_BOT_USERNAME")

    # ── PocketOption WS API ──
    # Full 42["auth",{...}] string copied from browser; demo/live encoded in it.
    po_ssid: str = Field(default="", alias="PO_SSID")

    # ── Gating thresholds ──
    min_channel_win_rate: float = Field(
        default=0.80, alias="MIN_CHANNEL_WIN_RATE", ge=0.0, le=1.0
    )
    min_tracked_win_rate: float = Field(
        default=0.55, alias="MIN_TRACKED_WIN_RATE", ge=0.0, le=1.0
    )
    min_tracked_samples: int = Field(default=20, alias="MIN_TRACKED_SAMPLES", ge=1)

    @field_validator("trade_mode", mode="before")
    @classmethod
    def _force_demo_if_unset(cls, v):
        if v is None:
            return TradeMode.DEMO
        mode = str(v).strip().upper()
        if mode not in (TradeMode.DEMO, TradeMode.LIVE):
            raise SettingsError(f"Invalid TRADE_MODE: {v!r}. Must be DEMO or LIVE.")
        return TradeMode(mode)

    model_config = ConfigDict(
        env_file=_PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # allow extra env vars without error
    )

    def __init__(self, **data):
        super().__init__(**data)
        # Extra safety: hard-reset to DEMO if the env var is missing or empty.
        if "trade_mode" not in data:
            object.__setattr__(self, "trade_mode", TradeMode.DEMO)


# Global singleton for convenience (import once)
settings = BotSettings()
