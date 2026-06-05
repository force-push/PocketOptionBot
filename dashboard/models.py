"""Pydantic response/event models for the dashboard API (docs §4).

Imported only on the FastAPI server side. Kept permissive (Optional defaults,
``extra='allow'`` on the event payloads) so it never rejects valid analytics
output while still documenting the contract.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ActiveTrade(BaseModel):
    trade_id: Optional[str] = None
    pair_raw: Optional[str] = None
    pair_api: Optional[str] = None
    dir: Optional[str] = None
    stake: Optional[float] = None
    entry: Optional[float] = None
    opened_at: Optional[str] = None
    expiry_at: Optional[str] = None
    expiry_seconds: Optional[int] = None
    confluence_n: Optional[int] = None
    confluence_score: Optional[float] = None


class Kpis(BaseModel):
    today_pnl: float = 0.0
    today_pnl_pct: Optional[float] = None
    win_rate: float = 0.0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    active_count: int = 0
    at_risk: float = 0.0
    trades_today: int = 0
    traded: int = 0
    skipped: int = 0
    avg_confluence: float = 0.0


class StateResponse(BaseModel):
    mode: str = "DEMO"
    dry_run: bool = True
    connected: bool = False
    balance: Optional[float] = None
    currency: str = "USD"
    kpis: Kpis = Field(default_factory=Kpis)
    active: list[dict] = Field(default_factory=list)
    ts: Optional[str] = None


class HistoryRow(BaseModel):
    ts: Optional[str] = None
    time: Optional[str] = None
    pair_raw: Optional[str] = None
    pair_api: Optional[str] = None
    otc: bool = False
    dir: Optional[str] = None
    decision: Optional[str] = None
    result: Optional[str] = None
    pnl: Optional[float] = None
    stake: Optional[float] = None
    expiry_seconds: Optional[int] = None
    our_confluence: Optional[float] = None
    bot_win_rate: Optional[float] = None
    entry: Optional[Any] = None
    skip_reason: Optional[str] = None
    trade_id: Optional[str] = None


class HistoryResponse(BaseModel):
    rows: list[HistoryRow] = Field(default_factory=list)
    next_before: Optional[str] = None


class EquityPoint(BaseModel):
    t: Optional[str] = None
    cum_pnl: float = 0.0


class WinLoss(BaseModel):
    wins: int = 0
    losses: int = 0
    draws: int = 0


class PairStat(BaseModel):
    pair: str
    pnl: float = 0.0
    wins: int = 0
    losses: int = 0


class PerformanceResponse(BaseModel):
    range: str = "ALL"
    equity: list[EquityPoint] = Field(default_factory=list)
    winloss: WinLoss = Field(default_factory=WinLoss)
    by_pair: list[PairStat] = Field(default_factory=list)


class SettingsUpdateRequest(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    confirm_live: bool = False


class SettingsUpdateResponse(BaseModel):
    ok: bool
    applied: dict[str, Any] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    requires_restart: list[str] = Field(default_factory=list)


class WsEnvelope(BaseModel):
    """Server → client WS frame (docs §4.3)."""
    type: str
    data: dict = Field(default_factory=dict)


__all__ = [
    "ActiveTrade", "Kpis", "StateResponse", "HistoryRow", "HistoryResponse",
    "EquityPoint", "WinLoss", "PairStat", "PerformanceResponse",
    "SettingsUpdateRequest", "SettingsUpdateResponse", "WsEnvelope",
]
