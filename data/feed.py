"""Price feed: maintains rolling OHLCV candle history."""

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from config.settings import settings


@dataclass(frozen=True)
class Tick:
    timestamp: datetime
    price: float


@dataclass
class OHLCV:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0

    def to_dict(self) -> dict:
        return {
            "time": self.timestamp.isoformat(),
            "o": self.open,
            "h": self.high,
            "l": self.low,
            "c": self.close,
            "v": self.volume,
        }


class PriceFeed:
    """Poll price from scraper, build candles, emit events."""

    def __init__(self, scraper, candle_interval: int | None = None):
        self._scraper = scraper
        self._candle_interval = candle_interval or settings.candle_interval_seconds
        self._history_length = settings.history_length

        self._ticks: deque[Tick] = deque()
        self._current_candle_start: datetime | None = None
        self._candles: deque[OHLCV] = deque(maxlen=self._history_length)

        self._on_new_candle_cbs = []
        self._on_tick_cbs = []

    @property
    def df(self) -> pd.DataFrame:
        if not self._candles:
            return pd.DataFrame()
        data = [c.to_dict() for c in self._candles]
        df = pd.DataFrame(data)
        df["time"] = pd.to_datetime(df["time"])
        return df.set_index("time")

    def on_new_candle(self, callback) -> None:
        self._on_new_candle_cbs.append(callback)

    def on_tick(self, callback) -> None:
        self._on_tick_cbs.append(callback)

    async def start(self) -> None:
        poll_interval = self._candle_interval / 10
        self._current_candle_start = datetime.now()

        try:
            while True:
                try:
                    price = await self._scraper.current_price()
                    if price is not None:
                        tick = Tick(datetime.now(), price)
                        await self._process_tick(tick)
                except Exception:
                    pass
                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            pass

    async def _process_tick(self, tick: Tick) -> None:
        self._ticks.append(tick)

        for cb in self._on_tick_cbs:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(tick)
                else:
                    cb(tick)
            except Exception:
                pass

        if self._current_candle_start is None:
            self._current_candle_start = tick.timestamp

        elapsed = (tick.timestamp - self._current_candle_start).total_seconds()
        if elapsed >= self._candle_interval:
            candle = self._close_candle()
            if candle:
                self._candles.append(candle)
                for cb in self._on_new_candle_cbs:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(candle)
                        else:
                            cb(candle)
                    except Exception:
                        pass
            self._current_candle_start = tick.timestamp

    def _close_candle(self) -> OHLCV | None:
        if not self._ticks:
            return None

        prices = [t.price for t in self._ticks]
        candle = OHLCV(
            timestamp=self._current_candle_start or datetime.now(),
            open=prices[0],
            high=max(prices),
            low=min(prices),
            close=prices[-1],
            volume=len(prices),
        )
        self._ticks.clear()
        return candle
