"""Loguru setup for the PocketOption bot."""

import json
import sys
from pathlib import Path

from loguru import logger as log

_TRADES_FILE: Path | None = None
LEVEL = "INFO"


def setup_logger(project_root: Path, level: str = "INFO") -> None:
    """Configure Loguru with file + stdout sinks."""
    global _TRADES_FILE, LEVEL  # noqa: PLW0603
    LEVEL = level

    log.remove()
    # stdout with time + level + message
    log.add(
        sys.stdout,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
               "{message}",
        colorize=True,
    )
    # File output (no colors)
    log.add(
        project_root / "logs" / "bot.log",
        level="DEBUG",
        rotation="1 day",
        retention="7 days",
        encoding="utf-8",
    )

    _TRADES_FILE = project_root / "data" / "trades.jsonl"
    _TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)


def log_trade(trade_result: dict) -> None:
    """Append a trade record to the trades.jsonl log file."""
    if _TRADES_FILE is None:
        raise RuntimeError("Logger not initialized. Call setup_logger() first.")

    with _TRADES_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(trade_result, default=str) + "\n")

    log.info("Trade logged: {id} {direction} ${amount}", **trade_result)
