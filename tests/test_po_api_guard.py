"""Tests for broker/po_api.py — demo guard and DRY_RUN gate.

All offline — no SSID, no network, no real API library required.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broker.po_api import (
    PocketOptionAPIClient,
    TradeResult,
    _parse_ssid_is_demo,
)
from config.settings import TradeMode


# ── SSID parser tests ─────────────────────────────────────────────────────────

def test_parse_ssid_is_demo_true():
    ssid = '42["auth",{"session":"abc","isDemo":1,"uid":123}]'
    assert _parse_ssid_is_demo(ssid) is True


def test_parse_ssid_is_demo_false():
    ssid = '42["auth",{"session":"abc","isDemo":0,"uid":123}]'
    assert _parse_ssid_is_demo(ssid) is False


def test_parse_ssid_truthy_value():
    ssid = '42["auth",{"session":"abc","isDemo":true}]'
    assert _parse_ssid_is_demo(ssid) is True


def test_parse_ssid_missing_isDemo():
    ssid = '42["auth",{"session":"abc"}]'
    assert _parse_ssid_is_demo(ssid) is None


def test_parse_ssid_empty():
    assert _parse_ssid_is_demo("") is None


def test_parse_ssid_garbage():
    assert _parse_ssid_is_demo("not a valid ssid") is None


# ── Demo guard: TRADE_MODE=DEMO, SSID=live → must abort ──────────────────────

@pytest.mark.asyncio
async def test_demo_guard_aborts_when_ssid_is_live(monkeypatch):
    """TRADE_MODE=DEMO but SSID isDemo=0 → trade should be aborted with ERROR."""
    ssid_live = '42["auth",{"session":"abc","isDemo":0}]'

    monkeypatch.setattr("config.settings.settings.trade_mode", TradeMode.DEMO)
    monkeypatch.setattr("config.settings.settings.dry_run", False)

    client = PocketOptionAPIClient(ssid=ssid_live, dry_run=False)
    # Give it a fake underlying client so we can confirm it's never called
    fake_api = AsyncMock()
    client._client = fake_api

    result = await client.buy("EURUSD_otc", 1.0, 60)
    assert result.status == "ERROR"
    assert "ABORT" in result.error or "isDemo=0" in result.error
    # The real API should NOT have been called
    fake_api.buy.assert_not_called()


@pytest.mark.asyncio
async def test_demo_guard_aborts_when_ssid_unparseable(monkeypatch):
    """TRADE_MODE=DEMO and SSID cannot be parsed → abort for safety."""
    monkeypatch.setattr("config.settings.settings.trade_mode", TradeMode.DEMO)
    monkeypatch.setattr("config.settings.settings.dry_run", False)

    client = PocketOptionAPIClient(ssid="garbage_ssid", dry_run=False)
    fake_api = AsyncMock()
    client._client = fake_api

    result = await client.buy("EURUSD_otc", 1.0, 60)
    assert result.status == "ERROR"
    fake_api.buy.assert_not_called()


@pytest.mark.asyncio
async def test_demo_guard_passes_when_ssid_is_demo(monkeypatch, tmp_path):
    """TRADE_MODE=DEMO and SSID isDemo=1 → guard passes, real API called."""
    ssid_demo = '42["auth",{"session":"abc","isDemo":1}]'

    monkeypatch.setattr("config.settings.settings.trade_mode", TradeMode.DEMO)
    monkeypatch.setattr("config.settings.settings.dry_run", False)

    # Initialise the trades file so log_trade doesn't raise
    import utils.logger as logger_mod
    logger_mod._TRADES_FILE = tmp_path / "trades.jsonl"
    logger_mod._TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)

    client = PocketOptionAPIClient(ssid=ssid_demo, dry_run=False)

    fake_trade_id = "trade_001"
    fake_deal = {"id": fake_trade_id}
    fake_api = AsyncMock()
    fake_api.buy = AsyncMock(return_value=(fake_trade_id, fake_deal))
    client._client = fake_api

    result = await client.buy("EURUSD_otc", 1.0, 60)
    assert result.status == "PENDING"
    assert result.trade_id == fake_trade_id
    fake_api.buy.assert_awaited_once_with("EURUSD_otc", 1.0, 60)


# ── DRY_RUN gate ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_skips_api(monkeypatch, tmp_path):
    """DRY_RUN=True → log the trade but do NOT call the library."""
    ssid_demo = '42["auth",{"session":"abc","isDemo":1}]'

    monkeypatch.setattr("config.settings.settings.trade_mode", TradeMode.DEMO)
    monkeypatch.setattr("config.settings.settings.dry_run", True)

    # Point log_trade at a temp file so we don't need the logger setup
    import utils.logger as logger_mod
    logger_mod._TRADES_FILE = tmp_path / "trades.jsonl"
    logger_mod._TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)

    client = PocketOptionAPIClient(ssid=ssid_demo, dry_run=True)
    fake_api = AsyncMock()
    client._client = fake_api

    result = await client.buy("EURUSD_otc", 1.0, 60)
    assert result.status == "DRY_RUN"
    fake_api.buy.assert_not_called()


@pytest.mark.asyncio
async def test_dry_run_sell_skips_api(monkeypatch, tmp_path):
    ssid_demo = '42["auth",{"session":"abc","isDemo":1}]'
    monkeypatch.setattr("config.settings.settings.trade_mode", TradeMode.DEMO)
    monkeypatch.setattr("config.settings.settings.dry_run", True)

    import utils.logger as logger_mod
    logger_mod._TRADES_FILE = tmp_path / "trades.jsonl"
    logger_mod._TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)

    client = PocketOptionAPIClient(ssid=ssid_demo, dry_run=True)
    fake_api = AsyncMock()
    client._client = fake_api

    result = await client.sell("GBPUSD_otc", 2.0, 300)
    assert result.status == "DRY_RUN"
    assert result.direction == "PUT"
    fake_api.sell.assert_not_called()


# ── Import without native wheel ───────────────────────────────────────────────

def test_module_imports_without_library():
    """broker/po_api must be importable even without binaryoptionstoolsv2."""
    import broker.po_api  # noqa: F401 — just confirm no ImportError


def test_client_instantiates_without_library():
    """PocketOptionAPIClient() must not raise at construction time."""
    client = PocketOptionAPIClient(ssid='42["auth",{"session":"x","isDemo":1}]')
    assert client is not None
