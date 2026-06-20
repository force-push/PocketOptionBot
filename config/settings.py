"""Pydantic-based configuration for ArgusSentinel."""

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
    # Per-pair post-loss cooldown: after a pair loses, skip RE-ENTERING that pair
    # for this many seconds (the poll loop / FocusSession trade other pairs in the
    # meantime — no idle time). Data: trades <60s after a loss on a pair ~42% WR.
    # 0 disables. Distinct from cooldown_after_loss_seconds (a global pause).
    post_loss_pair_cooldown_seconds: int = Field(default=60, alias="POST_LOSS_PAIR_COOLDOWN_SECONDS", ge=0)
    # Performance-based long cooldown: bench a pair for perf_cooldown_hours if its
    # rolling WR over the last perf_cooldown_window_hours falls below perf_cooldown_max_wr
    # after at least perf_cooldown_min_trades. Replaces permanent blocklist additions.
    perf_cooldown_min_trades: int = Field(default=3, alias="PERF_COOLDOWN_MIN_TRADES", ge=1)
    perf_cooldown_max_wr: float = Field(default=0.40, alias="PERF_COOLDOWN_MAX_WR", ge=0.0, le=1.0)
    perf_cooldown_window_hours: float = Field(default=3.0, alias="PERF_COOLDOWN_WINDOW_HOURS", gt=0)
    perf_cooldown_hours: float = Field(default=12.0, alias="PERF_COOLDOWN_HOURS", gt=0)

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

    # ── Risk ──
    dry_run: bool = Field(default=True, alias="DRY_RUN")
    max_open_trades: int = Field(default=6, alias="MAX_OPEN_TRADES", ge=1)
    trade_stagger_seconds: int = Field(default=5, alias="TRADE_STAGGER_SECONDS", ge=0)
    min_balance_multiplier: float = Field(default=5.0, alias="MIN_BALANCE_MULTIPLIER", ge=1.0)

    # (Telegram/Telethon settings removed 2026-06-12 — signals loop only)

    # ── PocketOption WS API ──
    # Full 42["auth",{...}] string copied from browser; demo/live encoded in it.
    po_ssid: str = Field(default="", alias="PO_SSID")

    # ── v2 (Telebot evolution) ──
    stake_amount: float = Field(default=1.5, alias="STAKE_AMOUNT", gt=0)
    default_expiry_seconds: int = Field(default=30, alias="DEFAULT_EXPIRY_SECONDS", gt=0)
    allowed_expiries: tuple[int, ...] = (5, 10, 15, 30, 50, 60, 80, 120, 128, 216, 300)
    # Minimum payout % from PocketOption for a trade to proceed. 0 disables the gate.
    # Set to 92 to only trade when PO is offering ≥92% profit on a win.
    min_payout_pct: int = Field(default=88, alias="MIN_PAYOUT_PCT", ge=0, le=100)
    # EV gate: minimum expected value to trade. EV = win_rate*(payout/100+1) - 1.
    # 0.0 = break-even required; -0.05 = allow 5% below break-even (warmup tolerance).
    # Gate only activates when n_tracked >= min_ev_samples (cold-start pass-through).
    min_expected_value: float = Field(default=0.0, alias="MIN_EXPECTED_VALUE", ge=-1.0, le=1.0)
    min_ev_samples: int = Field(default=15, alias="MIN_EV_SAMPLES", ge=1)
    # Martingale: after N consecutive losses on a pair, double the stake for the
    # next trade on that pair. Resets to base_stake on a win. Gated on the pair's
    # live WR being above break-even so we only chase recoverable sequences.
    # Default off — enable only after validating base strategy in demo.
    martingale_enabled: bool = Field(default=False, alias="MARTINGALE_ENABLED")
    martingale_max_level: int = Field(default=3, alias="MARTINGALE_MAX_LEVEL", ge=1, le=6)
    martingale_min_pair_wr: float = Field(default=0.521, alias="MARTINGALE_MIN_PAIR_WR", ge=0.0, le=1.0)
    martingale_min_wr_samples: int = Field(default=10, alias="MARTINGALE_MIN_WR_SAMPLES", ge=1)
    decisions_log_path: str = Field(default="data/decisions.jsonl", alias="DECISIONS_LOG_PATH")
    # SQLite decision store — the live data path (fast INSERT/UPDATE, indexed
    # reads). Replaces append-and-rewrite of decisions.jsonl, which became O(N²)
    # at scale. The .jsonl above is retained only as the migration source/archive.
    decisions_db_path: str = Field(default="data/decisions.db", alias="DECISIONS_DB_PATH")
    # List of pair_api values (e.g., "EURUSD_otc") to block at pair selection.
    # This prevents wasting time on analysis for known underperforming pairs.
    # Empirical losers to skip even when the bot rates them highly (2026-06-09 research,
    # n>=8 each). See docs/signal-strategy-research.md.
    blocked_pairs: list[str] = Field(
        default=["EURUSD_otc", "ETHUSD_otc", "AUDCHF_otc", "USDARS_otc",
                 "EURTRY_otc", "USDPHP_otc", "CHFNOK_otc"],
        alias="BLOCKED_PAIRS",
    )

    # ── SuperTrend-flip strategy (2026-06-14) ────────────────────────────────
    # strategy_mode selects the decision engine:
    #   "confluence" — the legacy 11-signal weighted vote (decision.py path).
    #   "flip"       — SuperTrend flip / strong-trend continuation, confirmed by
    #                  MACD + ADX movement (strategy/flip_strategy.py).
    strategy_mode: str = Field(default="flip", alias="STRATEGY_MODE")
    # Curated high-payout OTC allowlist (FX + crypto). When non-empty, the scan
    # trades ONLY these symbols (and ignores blocked_pairs for them). Each still
    # honours MIN_PAYOUT_PCT, so sub-floor entries sit idle until payout rises.
    allowed_pairs: list[str] = Field(
        default=[
            "EURUSD_otc", "USDJPY_otc", "AEDCNY_otc", "EURCHF_otc",
            "USDMXN_otc", "ZARUSD_otc", "GBPUSD_otc", "AUDUSD_otc",
            "DOGE_otc", "ETHUSD_otc", "TRX-USD_otc", "BITB_otc",
        ],
        alias="ALLOWED_PAIRS",
    )
    # Pattern-based allowlist — when set, a pair is tradable only if this regex
    # matches its symbol (authoritative for both the poll loop and FocusSession,
    # blocklist still applies). Looser than the exact allowed_pairs list: e.g.
    # "(USD|CNY|CNH)" trades any USD/CNY/CNH cross. Empty = off.
    allowed_pair_regex: str = Field(default="", alias="ALLOWED_PAIR_REGEX")
    # One open trade per pair: don't re-enter a pair until its trade resolves
    # (~5s). Paces trend-continuation entries instead of firing every cycle.
    one_open_trade_per_pair: bool = Field(default=True, alias="ONE_OPEN_TRADE_PER_PAIR")
    # Flip-strategy parameters (live-tunable; calibrate on DEMO results).
    st_period: int = Field(default=10, alias="ST_PERIOD", ge=1)
    st_multiplier: float = Field(default=3.0, alias="ST_MULTIPLIER", gt=0)
    flip_adx_min: float = Field(default=22.0, alias="FLIP_ADX_MIN", ge=0)
    trend_adx_min: float = Field(default=25.0, alias="TREND_ADX_MIN", ge=0)
    # Upper ADX cap — skip entries above this (over-extended/exhausted moves
    # revert inside 5s; data 2026-06-14: ADX 45+ ~17% WR vs 25-35 ~61%). This is
    # the committed baseline; data/flip_levers.json overrides it live (no restart).
    flip_adx_max: float = Field(default=40.0, alias="FLIP_ADX_MAX", ge=0)
    trend_require_adx_rising: bool = Field(default=True, alias="TREND_REQUIRE_ADX_RISING")
    trend_atr_distance_min: float = Field(default=0.5, alias="TREND_ATR_DISTANCE_MIN", ge=0)
    # Continuation MACD-momentum gate: require |MACD-signal|/ATR ≥ this for trend
    # continuation entries (the trend "runs off the MACD"; data: large-gap
    # continuations ~53% WR vs small-gap ~47%). 0 = off; tune via levers file.
    cont_macd_gap_min: float = Field(default=0.5, alias="CONT_MACD_GAP_MIN", ge=0)
    # Treat a flip as "fresh" if the SuperTrend trend started within this many of
    # the most recent 1s bars. >1 catches flips the ~cycle-cadence scan would
    # otherwise miss (the flip is a 1-bar event sampled every few seconds).
    flip_window_bars: int = Field(default=3, alias="FLIP_WINDOW_BARS", ge=1)
    # Max concurrent history(1) candle fetches per cycle. Parallel prefetch lets
    # the scan evaluate each pair more often (catch flips sooner). Capped to avoid
    # the WS-hang seen with unbounded concurrency (see git history 2026-06-13).
    candle_fetch_concurrency: int = Field(default=3, alias="CANDLE_FETCH_CONCURRENCY", ge=1)
    # Event-driven flip streamer (strategy/flip_streamer.py): subscribe to live 1s
    # candle streams for STREAMING_PAIRS and place fresh flips at the turn (~1s)
    # instead of the ~6s poll cadence. OFF by default (concurrent WS streams carry
    # hang risk — validate live before relying on it). Streamed pairs are excluded
    # from the poll scan. Cap ~4 concurrent subscriptions.
    streaming_enabled: bool = Field(default=False, alias="STREAMING_ENABLED")
    streaming_pairs: list[str] = Field(
        default=["EURUSD_otc", "AUDUSD_otc", "GBPUSD_otc", "DOGE_otc"],
        alias="STREAMING_PAIRS",
    )
    # ── Focus-session manager (strategy/focus_session.py) ────────────────────
    # When enabled, a background task locks onto the highest-payout allowed pair,
    # subscribes to its raw tick stream, trades N flips, then rotates to the next
    # best pair.  The current focus pair is excluded from the poll loop scan.
    # OFF by default — validate alongside the poll loop before relying on it.
    focus_session_enabled: bool = Field(default=False, alias="FOCUS_SESSION_ENABLED")
    # Trades to place per pair before rotating.  After this many placements the
    # session unsubscribes and re-ranks.  A forced rotation also fires after
    # 300s so a quiet pair never blocks the queue indefinitely.
    focus_session_trades: int = Field(default=10, alias="FOCUS_SESSION_TRADES", ge=1)
    # Payout floor for FocusSession pair selection — typically higher than the
    # global min_payout_pct because FocusSession only wants top-tier pairs.
    # Pairs that drop below this mid-session trigger immediate rotation.
    focus_payout_floor: int = Field(default=90, alias="FOCUS_PAYOUT_FLOOR", ge=0, le=100)
    # When True, FocusSession only considers forex pairs (6-char alpha OTC symbols).
    # Stocks (# prefix), indices (VIX), and crypto (BTC/ETH/BNB prefixes, dashes)
    # are excluded.  Stocks behave differently at intra-minute scale — news gaps,
    # circuit breakers, and thin spreads make SuperTrend signals unreliable.
    focus_fx_only: bool = Field(default=True, alias="FOCUS_FX_ONLY")
    # Minimum average ticks per 1s bar for a pair to be considered liquid.
    # Illiquid pairs (too few ticks) produce noisy/flat OHLC bars — the
    # SuperTrend/MACD indicators fire on microstructure rather than real moves.
    # Pairs below this rate are cooled off for 5 minutes before being re-tried.
    focus_min_tick_rate: float = Field(default=2.0, alias="FOCUS_MIN_TICK_RATE", ge=0.1)

    # Research/data-collection mode. When True AND trade_mode == DEMO, the bot
    # stops *blocking* trades at the TA-agreement, EV, and risk gates: it places
    # the bot-direction trade anyway and records the outcome, tagging the row with
    # shadow=True and would_skip_reason. This builds an UNCENSORED dataset (we
    # otherwise only ever see outcomes for trades that passed every gate).
    # HARD GUARD: ignored in LIVE — it can never widen real-money trading.
    # The low_payout gate is still enforced to keep demo economics comparable.
    shadow_record_mode: bool = Field(default=False, alias="SHADOW_RECORD_MODE")

    # Shadow expiry experiment (signals loop only). For each real signals-loop
    # trade, also place demo trades at these expiries (same pair + direction,
    # shadow=True, shadow_kind="expiry") to compare win rate across durations.
    # Empty list disables. Shadow trades NEVER feed the production win-rate
    # tracker or risk stats, and never consume the real concurrency budget.
    # HARD GUARD: ignored in LIVE — research only, demo balance only.
    shadow_expiry_seconds: list[int] = Field(default=[], alias="SHADOW_EXPIRY_SECONDS")

    # 5s timeframe shadow track: evaluate SuperTrend flips on 5s candles alongside
    # the 1s live strategy. When a 5s signal fires, place shadow trades at each
    # expiry in shadow_tf5s_expiry_seconds (shadow_kind="tf5s"). Levers read from
    # data/flip_levers_5s.json (mtime-cached, same mechanic as flip_levers.json).
    # 5s candles are fetched in a second prefetch pass after the 1s pass.
    # HARD GUARD: ignored in LIVE — research/shadow only.
    shadow_tf5s_enabled: bool = Field(default=False, alias="SHADOW_TF5S_ENABLED")
    shadow_tf5s_expiry_seconds: list[int] = Field(default=[15, 30], alias="SHADOW_TF5S_EXPIRY_SECONDS")

    # Time-of-day hour gating (signals loop only). DISABLED by default since
    # 2026-06-11: the static hour table was curve-fit to one day's noise —
    # hour win rates did not replicate across days (SHADOW_TRADE_ANALYSIS.md
    # Finding 5 + Addendum 3). Set true to re-enable the TimeOfDayFilter.
    time_of_day_filter_enabled: bool = Field(
        default=False, alias="TIME_OF_DAY_FILTER_ENABLED"
    )

    # Shadow-trade blocked hours (signals loop only). When true, cycles during
    # hours blocked by the time-of-day filter still run, but every trade that
    # passes the signal gates is placed as a SHADOW trade (shadow=True,
    # shadow_kind="time_of_day") instead of a real strategy trade. Collects
    # signal-outcome data across all 24 hours without risking the strategy's
    # win rate. Default false = blocked hours are fully skipped (no trades).
    # HARD GUARD: shadows never placed in LIVE — research only, demo balance.
    shadow_trade_blocked_hours: bool = Field(
        default=False, alias="SHADOW_TRADE_BLOCKED_HOURS"
    )

    # Fade-rule shadow experiment (SHADOW_TRADE_ANALYSIS.md Finding 4a):
    # when >= this many signals agree on one direction, place a shadow in the
    # OPPOSITE direction (shadow_kind="fade"). Unanimity among our correlated
    # trend signals marks exhaustion; fading it measured ~53% WR. 0 = disabled.
    shadow_fade_min_agree: int = Field(
        default=7, alias="SHADOW_FADE_MIN_AGREE", ge=0
    )

    # ADX-regime shadow experiment (Finding 4b): when ADX_DMI confidence is
    # >= this value, place a shadow FOLLOWING the ADX direction
    # (shadow_kind="adx_regime"). High ADX = strong trend; measured ~57% WR
    # at conf >= 0.6 (n=110). 0 = disabled.
    shadow_adx_regime_min_conf: float = Field(
        default=0.6, alias="SHADOW_ADX_REGIME_MIN_CONF", ge=0.0, le=1.0
    )

    # Flip-skip shadow: when the flip strategy rejects a signal (MACD disagrees,
    # ADX dead zone, bb_width gate, etc.), place a shadow trade in the raw
    # SuperTrend direction to measure what would have happened without the gate.
    # Builds the dataset for validating/relaxing over-filtering gates.
    shadow_flip_skip_enabled: bool = Field(default=False, alias="SHADOW_FLIP_SKIP_ENABLED")

    # Real-OHLC feature flag (PO_DATA_SURFACE.md Step 2).
    # True  → use history() for genuine wicks (HeikinAshi/ATR/Supertrend benefit).
    # False → use the proven-stable get_candles() flat-snapshot path (default).
    # Defaulted OFF because history() adds latency and increases cycle-abort
    # frequency (~8-12min vs ~15-40min) at 30s expiry where wick-signals didn't
    # show measurable accuracy lift vs flat OHLC in shadow analysis. Turn ON when:
    #   - switching to longer expiries (≥120s) where candle structure matters, or
    #   - HeikinAshi/ATR demonstrate >54% directional accuracy on real vs flat OHLC,
    #   - or the underlying WS library makes history() as fast as get_candles().
    use_real_ohlc: bool = Field(default=False, alias="USE_REAL_OHLC")

    # ── Payout-First, Signals-Driven Loop (the only driver) ──
    # Max pairs to evaluate per cycle in signals mode (0 = all ≥ floor).
    max_pairs_per_cycle: int = Field(default=0, alias="MAX_PAIRS_PER_CYCLE", ge=0)

    # ── Tracked win-rate gate thresholds ──
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

    @field_validator("blocked_pairs", "allowed_pairs", "streaming_pairs", mode="before")
    @classmethod
    def _parse_pair_list(cls, v):
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
