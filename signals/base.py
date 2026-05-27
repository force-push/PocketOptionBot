"""Abstract base class for trading signals."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SignalResult:
    """Result from a single signal evaluation."""
    name: str
    direction: str | None  # "CALL", "PUT", or None
    confidence: float  # 0.0 to 1.0
    reason: str


class BaseSignal(ABC):
    """Base class for all trading signals."""

    name: str = "BaseSignal"
    weight: float = 0.0  # Contribution to confluence (0.0 to 1.0)

    @abstractmethod
    async def evaluate(self, df: pd.DataFrame) -> SignalResult:
        """Evaluate the signal on the latest OHLCV data.

        Args:
            df: DataFrame with columns: o, h, l, c, v (already indexed by time)

        Returns:
            SignalResult with direction (CALL/PUT/None), confidence, and reason
        """
        pass
