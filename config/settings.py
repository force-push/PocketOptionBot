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
    # Lowered from 0.75: with trend-direction MACD/EMA signals (see signals/macd.py,
    # ema_cross.py) real-world scores land in 0.25-0.60 for 3-4 agreeing signals.
    # 0.75 required near-perfect confidence from all signals simultaneously —
    # only achievable on fresh crossovers, blocking most valid trend entries.
    min_confluence_score: float = Field(
        default=0.35, alias="MIN_CONFLUENCE_SCORE", ge=0.0, le=1.0
    )
    # Minimum number of signals that must agree on the same direction.
    # Separate from the score floor: both gates must pass independently.
    # Set to 2 during initial calibration so trades reach execution and
    # real outcomes can inform threshold tuning. Raise to 3+ for stricter entries.
    min_signal_agreement: int = Field(default=3, alias="MIN_SIGNAL_AGREEMENT", ge=1, le=5)
    max_trades_per_hour: int = Field(default=10, alias="MAX_TRADES_PER_HOUR", ge=1)
    max_daily_loss_usd: float = Field(default=20.0, alias="MAX_DAILY_LOSS_USD", ge=0)
    # Candle resolution fed to TA signals. Deliberately decoupled from the trade
    # expiry — signals need fine-grained price action, not one candle per trade.
    # 5 s: 100 candles ≈ 8 min of context, fine-grained enough for 30 s expiry.
    # Previously defaulted to 60 s and was (incorrectly) overridden by expiry in
    # manager_v2.py; both bugs are now fixed.
    candle_interval_seconds: int = Field(default=5, alias="CANDLE_INTERVAL_SECONDS", ge=1)
    history_length: int = Field(default=100, alias="HISTORY_LENGTH", ge=10)
    cooldown_after_loss_seconds: int = Field(default=120, alias="COOLDOWN_AFTER_LOSS_SECONDS", ge=0)

    # ── Per-signal parameters (wired into signal constructors in main_v2.py) ──
    # Expose here so they can be tuned via .env or dashboard without code changes.
    rsi_period: int = Field(default=14, alias="RSI_PERIOD", ge=2)
    rsi_oversold: float = Field(default=30.0, alias="RSI_OVERSOLD", ge=1.0, le=49.0)
    rsi_overbought: float = Field(default=70.0, alias="RSI_OVERBOUGHT", ge=51.0, le=99.0)
    macd_fast: int = Field(default=12, alias="MACD_FAST", ge=2)
    macd_slow: int = Field(default=26, alias="MACD_SLOW", ge=3)
    macd_signal_period: int = Field(default=9, alias="MACD_SIGNAL_PERIOD", ge=2)
    ema_fast: int = Field(default=9, alias="EMA_FAST", ge=2)
    ema_slow: int = Field(default=21, alias="EMA_SLOW", ge=3)
    bollinger_period: int = Field(default=20, alias="BOLLINGER_PERIOD", ge=5)
    bollinger_std: float = Field(default=2.0, alias="BOLLINGER_STD", ge=0.5, le=5.0)

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

    # ── v2 (Telebot evolution) ──
    stake_amount: float = Field(default=1.5, alias="STAKE_AMOUNT", gt=0)
    default_expiry_seconds: int = Field(default=30, alias="DEFAULT_EXPIRY_SECONDS", gt=0)
    allowed_expiries: tuple[int, ...] = (5, 10, 15, 30, 60, 120, 300)
    # Navigation pair-selection gate. 0.0 DISABLES it (capture/testing — no trades happen);
    # set to 0.82 for real runs (the "82%" rule).
    pair_select_min_win_rate: float = Field(default=0.0, alias="PAIR_SELECT_MIN_WIN_RATE", ge=0.0, le=1.0)
    # Minimum payout % from PocketOption for a trade to proceed. 0 disables the gate.
    # Set to 92 to only trade when PO is offering ≥92% profit on a win.
    min_payout_pct: int = Field(default=92, alias="MIN_PAYOUT_PCT", ge=0, le=100)
    # EV gate: minimum expected value to trade. EV = win_rate*(payout/100+1) - 1.
    # 0.0 = break-even required; -0.05 = allow 5% below break-even (warmup tolerance).
    # Gate only activates when n_tracked >= min_ev_samples (cold-start pass-through).
    min_expected_value: float = Field(default=0.0, alias="MIN_EXPECTED_VALUE", ge=-1.0, le=1.0)
    min_ev_samples: int = Field(default=15, alias="MIN_EV_SAMPLES", ge=1)
    click_trade_anyway: bool = Field(default=True, alias="CLICK_TRADE_ANYWAY")
    decisions_log_path: str = Field(default="data/decisions.jsonl", alias="DECISIONS_LOG_PATH")
    # List of pair_api values (e.g., "EURUSD_otc") to block at pair selection.
    # This prevents wasting time on analysis for known underperforming pairs.
    # Empirical losers to skip even when the bot rates them highly (2026-06-09 research,
    # n>=8 each). See docs/signal-strategy-research.md.
    blocked_pairs: list[str] = Field(
        default=["EURUSD_otc", "ETHUSD_otc", "AUDCHF_otc", "USDARS_otc",
                 "EURTRY_otc", "USDPHP_otc", "CHFNOK_otc"],
        alias="BLOCKED_PAIRS",
    )
    # Research/data-collection mode. When True AND trade_mode == DEMO, the bot
    # stops *blocking* trades at the TA-agreement, EV, and risk gates: it places
    # the bot-direction trade anyway and records the outcome, tagging the row with
    # shadow=True and would_skip_reason. This builds an UNCENSORED dataset (we
    # otherwise only ever see outcomes for trades that passed every gate).
    # HARD GUARD: ignored in LIVE — it can never widen real-money trading.
    # The low_payout gate is still enforced to keep demo economics comparable.
    shadow_record_mode: bool = Field(default=False, alias="SHADOW_RECORD_MODE")

    # ── Legacy gating thresholds (v1 CDP path, NOT in v2 live path) ──
    # v2 uses confluence engine gates (min_signal_agreement + min_confluence_score).
    # These are kept for backward compat but NOT exposed in dashboard, NOT used
    # in main_v2.py, and NOT visible in Settings panel.
    min_channel_win_rate: float = Field(
        default=0.80, alias="MIN_CHANNEL_WIN_RATE", ge=0.0, le=1.0
    )
    min_tracked_win_rate: float = Field(
        default=0.55, alias="MIN_TRACKED_WIN_RATE", ge=0.0, le=1.0
    )
    min_tracked_samples: int = Field(default=20, alias="MIN_TRACKED_SAMPLES", ge=1)

    # ── Dashboard (read-mostly web UI; off by default, no behavioural impact) ──
    dashboard_enabled: bool = Field(default=False, alias="DASHBOARD_ENABLED")
    dashboard_host: str = Field(default="127.0.0.1", alias="DASHBOARD_HOST")
    dashboard_port: int = Field(default=8787, alias="DASHBOARD_PORT", ge=1, le=65535)
    dashboard_token: Optional[str] = Field(default=None, alias="DASHBOARD_TOKEN")
    live_state_path: str = Field(default="data/live_state.json", alias="LIVE_STATE_PATH")
    events_log_path: str = Field(default="data/events.jsonl", alias="EVENTS_LOG_PATH")

    @field_validator("trade_mode", mode="before")
    @classmethod
    def _force_demo_if_unset(cls, v):
        if v is None:
            return TradeMode.DEMO
        mode = str(v).strip().upper()
        if mode not in (TradeMode.DEMO, TradeMode.LIVE):
            raise SettingsError(f"Invalid TRADE_MODE: {v!r}. Must be DEMO or LIVE.")
        return TradeMode(mode)

    @field_validator("telegram_session", mode="before")
    @classmethod
    def _expand_session_path(cls, v):
        # Telethon does NOT expand ~ in session paths; expand it here so a path
        # like ~/.telebot/telegram.session resolves instead of creating a literal
        # "~" file (which would trigger a fresh, interactive auth).
        if isinstance(v, str) and v.startswith("~"):
            return str(Path(v).expanduser())
        return v

    @field_validator("blocked_pairs", mode="before")
    @classmethod
    def _parse_blocked_pairs(cls, v):
        # Accept comma-separated string or list; normalize to list
        if v is None:
            return []
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

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
