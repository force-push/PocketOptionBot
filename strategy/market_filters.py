"""Time-of-day and pair filters to improve trading win rate.

Analysis (2026-06-10, n=854 trades) showed:
  - Time-of-day effect: 11:00 UTC has 90.9% WR, 23:00 has 31.4% WR (40% swing)
  - Pair effect: QARCNY 58.6% WR, BTCUSD 38.7% WR (20% swing)

Filters are based on empirical win-rate data, not theoretical assumptions.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from utils.logger import log


class TimeOfDayFilter:
    """Skip trades outside profitable hours."""

    # Win rate by hour (UTC). Threshold: only trade when WR > 52% break-even.
    PROFITABLE_HOURS = {
        6: 75.0,    # 06:00 UTC — excellent
        8: 58.8,    # 08:00 UTC — good
        9: 70.0,    # 09:00 UTC — excellent
        11: 90.9,   # 11:00 UTC — best
        17: 66.7,   # 17:00 UTC — good
        18: 53.1,   # 18:00 UTC — profitable
        20: 53.8,   # 20:00 UTC — profitable
    }

    BLOCKED_HOURS = {
        0: 0.0,     # 00:00 UTC — no data, too risky
        12: 39.3,   # 12:00 UTC — terrible
        14: 47.7,   # 14:00 UTC — below break-even
        16: 45.2,   # 16:00 UTC — bad
        19: 43.6,   # 19:00 UTC — bad
        23: 31.4,   # 23:00 UTC — worst
    }

    @classmethod
    def is_allowed(cls, utc_hour: int) -> bool:
        """Return True if current hour is profitable for trading."""
        # If hour is explicitly marked as profitable, allow it
        if utc_hour in cls.PROFITABLE_HOURS:
            return True

        # If hour is explicitly blocked, deny it
        if utc_hour in cls.BLOCKED_HOURS:
            return False

        # Unknown hours (7, 10, 13, 15, 21, 22): conservative — deny
        # (no data to support trading)
        return False

    @classmethod
    def current_hour(cls) -> int:
        """Return current UTC hour (0-23)."""
        return datetime.now(timezone.utc).hour

    @classmethod
    def skip_reason(cls, utc_hour: int) -> str | None:
        """Return skip reason if hour is blocked, else None."""
        if utc_hour in cls.BLOCKED_HOURS:
            return f"time_of_day_blocked (hour {utc_hour:02d}:00 UTC, WR {cls.BLOCKED_HOURS[utc_hour]:.1f}%)"
        if utc_hour not in cls.PROFITABLE_HOURS and utc_hour not in cls.BLOCKED_HOURS:
            return f"time_of_day_insufficient_data (hour {utc_hour:02d}:00 UTC)"
        return None


class PairWhitelistFilter:
    """Only trade pairs with proven win rates > 55%."""

    # Pairs with >55% win rate (25+ trades each) from empirical analysis
    WHITELIST = {
        "QARCNY_otc": 58.6,      # Qatari Riyal/Chinese Yuan
        "EURGBP_otc": 60.9,      # Euro/British Pound
        "YERUSD_otc": 55.6,      # Emirati Dirham or Israeli Shekel/USD
        "USDBDT_otc": 60.0,      # USD/Bangladesh Taka
    }

    # Pairs that consistently lose (< 40% WR, 15+ trades each)
    BLACKLIST = {
        "BTCUSD_otc": 38.7,      # Bitcoin — too volatile for synthetic
        "KESUSD_otc": 31.6,      # Kenyan Shilling — illiquid
        "LBPUSD_otc": 42.3,      # Lebanese Pound — pegged instability
        "UAHUSD_otc": 31.6,      # Ukrainian Hryvnia — illiquid/volatile
        "AEDCNY_otc": 45.8,      # AED/CNY — insufficient data
    }

    @classmethod
    def is_allowed(cls, pair_api: str) -> bool:
        """Return True if pair is in whitelist."""
        return pair_api in cls.WHITELIST

    @classmethod
    def skip_reason(cls, pair_api: str) -> str | None:
        """Return skip reason if pair is not allowed, else None."""
        if pair_api in cls.BLACKLIST:
            return f"pair_blacklist ({pair_api}, {cls.BLACKLIST[pair_api]:.1f}% WR)"
        if pair_api not in cls.WHITELIST:
            return f"pair_not_whitelisted ({pair_api})"
        return None


class PairHourBlocklist:
    """Skip (pair, UTC-hour-of-day) combinations that bled on historical data.

    Sharper than the bot-wide ``TimeOfDayFilter`` because the per-pair time
    structure can be inverted from the bot-wide trend (e.g. AUDUSD h14 = +71%
    WR while MADUSD h14 = 20% WR over the same window).

    Block list is loaded from ``data/pair_hour_blocks.json`` so updates do not
    require a code change. Empty file / missing file = no blocks (safe default).
    """

    _CACHE: "dict[str, frozenset[int]] | None" = None
    _PATH = Path(__file__).parent.parent / "data" / "pair_hour_blocks.json"

    @classmethod
    def _load(cls) -> "dict[str, frozenset[int]]":
        if cls._CACHE is not None:
            return cls._CACHE
        try:
            with cls._PATH.open("r", encoding="utf-8") as fh:
                doc = json.load(fh)
            blocks = doc.get("blocks") or {}
            cls._CACHE = {p: frozenset(hours) for p, hours in blocks.items()}
            log.info(
                "PairHourBlocklist loaded {} pair entries from {} (version {})",
                len(cls._CACHE), cls._PATH.name, doc.get("version"),
            )
        except FileNotFoundError:
            log.debug("PairHourBlocklist: {} missing — no blocks active", cls._PATH)
            cls._CACHE = {}
        except Exception as exc:
            log.warning("PairHourBlocklist: failed to load {} — no blocks active: {}", cls._PATH, exc)
            cls._CACHE = {}
        return cls._CACHE

    @classmethod
    def reload(cls) -> None:
        """Drop the cache so the next call re-reads the JSON file. Used for
        live updates without bot restart."""
        cls._CACHE = None

    @classmethod
    def is_blocked(cls, pair_api: str, utc_hour: int) -> bool:
        return utc_hour in cls._load().get(pair_api, frozenset())

    @classmethod
    def skip_reason(cls, pair_api: str, utc_hour: int) -> "str | None":
        if cls.is_blocked(pair_api, utc_hour):
            return f"pair_hour_block: {pair_api} @ {utc_hour:02d}:00 UTC"
        return None


def should_trade_cycle(utc_hour: int) -> bool:
    """Check if current cycle should proceed based on time filter.

    Args:
        utc_hour: Current hour in UTC (0-23)

    Returns:
        True if trading is allowed this hour, False otherwise.
    """
    return TimeOfDayFilter.is_allowed(utc_hour)


def should_trade_pair(pair_api: str) -> bool:
    """Check if specific pair should be traded.

    Args:
        pair_api: Pair symbol (e.g., "QARCNY_otc")

    Returns:
        True if pair is in whitelist, False otherwise.
    """
    return PairWhitelistFilter.is_allowed(pair_api)
