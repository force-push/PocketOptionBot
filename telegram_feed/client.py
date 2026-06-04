"""Telethon-based Telegram signal feed.

Imports Telethon lazily so the module can be imported even when Telethon is
not installed (e.g. during offline tests).
"""

from __future__ import annotations

import asyncio
from typing import Optional

from config.settings import settings
from utils.logger import log

# Lazy import guard — Telethon may not be installed in all environments
try:
    from telethon import TelegramClient, events as tg_events  # type: ignore[import]
    _TELETHON_AVAILABLE = True
except ImportError:
    _TELETHON_AVAILABLE = False
    TelegramClient = None  # type: ignore[assignment,misc]
    tg_events = None  # type: ignore[assignment]


class TelegramSignalFeed:
    """Listens to po_broker_bot DMs and pushes raw message text onto a queue.

    Usage:
        feed = TelegramSignalFeed()
        await feed.start()           # runs until cancelled

    The queue is available as feed.queue — consume it in the strategy manager.
    """

    def __init__(
        self,
        api_id: Optional[int] = None,
        api_hash: Optional[str] = None,
        phone: Optional[str] = None,
        session_name: Optional[str] = None,
        signal_bot_username: Optional[str] = None,
    ) -> None:
        self._api_id = api_id or settings.telegram_api_id
        self._api_hash = api_hash or settings.telegram_api_hash
        self._phone = phone or settings.telegram_phone
        self._session_name = session_name or settings.telegram_session
        self._signal_bot_username = signal_bot_username or settings.signal_bot_username

        # Public queue — consumers read raw message text from here
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._client: Optional[object] = None

    # ──────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Telegram and listen for new messages until cancelled.

        Raises RuntimeError if Telethon is not installed or credentials are
        missing.
        """
        if not _TELETHON_AVAILABLE:
            raise RuntimeError(
                "Telethon is not installed. "
                "Install it with: pip install telethon"
            )

        if not self._api_id or not self._api_hash:
            raise RuntimeError(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env "
                "before starting the Telegram feed."
            )

        log.info(
            "Starting Telegram feed (session=%s, bot=%s)",
            self._session_name,
            self._signal_bot_username,
        )

        client = TelegramClient(
            self._session_name,
            self._api_id,
            self._api_hash,
        )

        self._client = client

        try:
            await client.start(phone=self._phone)
            log.info("Telegram client connected")

            @client.on(tg_events.NewMessage(from_users=self._signal_bot_username))
            async def _on_message(event):
                text = event.raw_text or ""
                if text:
                    log.debug("Telegram signal received: %s", text[:80])
                    await self.queue.put(text)

            log.info(
                "Listening for messages from %s ...", self._signal_bot_username
            )
            await client.run_until_disconnected()

        except asyncio.CancelledError:
            log.info("Telegram feed cancelled — disconnecting")
            raise
        finally:
            if client.is_connected():
                await client.disconnect()
            log.info("Telegram client disconnected")
