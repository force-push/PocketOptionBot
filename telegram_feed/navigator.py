# telegram_feed/navigator.py
"""Drive po_broker_bot's inline-button UI to reach the direction screen.

Pure helpers (button matching / screen classification) are unit-tested.
Async `Navigator` methods perform Telethon I/O and are integration-tested.

Flow: start_autotrade → read prediction → select_pair → dismiss nag
      (Trade Anyway) → read direction screen → back_to_menu.
WE NEVER CLICK AN AMOUNT BUTTON — execution happens via the PocketOption API.
"""
from __future__ import annotations

import asyncio

from telegram_feed.pair_norm import normalize_pair
from utils.logger import log

try:
    from telethon.errors import FloodWaitError  # type: ignore
except Exception:  # pragma: no cover - telethon optional at import time
    class FloodWaitError(Exception):  # type: ignore
        seconds = 0

_NAG_MARKERS = ("tokens running low", "trade anyway")
_STAKE_MARKERS = ("select trade amount", "select the stake amount")
_DIR_MARKERS = ("direction:", "setup detected")


def find_pair_button_text(button_texts: list[str], pair_api: str) -> str | None:
    """Return the button label whose normalized pair == pair_api (skip Main Menu)."""
    for t in button_texts:
        if "main menu" in t.lower():
            continue
        if normalize_pair(t) == pair_api:
            return t
    return None


def is_nag_screen(text: str, button_texts: list[str]) -> bool:
    low = (text or "").lower()
    if any(m in low for m in _NAG_MARKERS):
        return True
    return any("trade anyway" in (b or "").lower() for b in button_texts)


def is_stake_selection_screen(text: str) -> bool:
    """Detect the stake amount selection screen (between direction and execution)."""
    low = (text or "").lower()
    return any(m in low for m in _STAKE_MARKERS)


def is_direction_screen(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _DIR_MARKERS) and "bot prediction" not in low


class Navigator:
    def __init__(self, client, bot_username: str, click_trade_anyway: bool = True):
        self._c = client
        self._bot = bot_username
        self._click_anyway = click_trade_anyway

    async def _recent(self, limit=10):
        msgs = []
        async for m in self._c.iter_messages(self._bot, limit=limit):
            btns = []
            if m.buttons:
                for row in m.buttons:
                    btns.extend(b.text for b in row if b and getattr(b, "text", None))
            msgs.append((m, m.text or "", btns))
        return msgs

    async def _click(self, predicate, limit=12) -> str | None:
        async for m in self._c.iter_messages(self._bot, limit=limit):
            if not m.buttons:
                continue
            for i, row in enumerate(m.buttons):
                for j, b in enumerate(row):
                    if b and getattr(b, "text", None) and predicate(b.text):
                        try:
                            await m.click(i, j)
                            return b.text
                        except FloodWaitError as e:
                            log.warning("FloodWait during click: sleeping {}s", getattr(e, "seconds", 0))
                            await asyncio.sleep(getattr(e, "seconds", 0) or 1)
                            raise
                        except Exception as e:
                            log.debug("click failed: {}", e)
        return None

    async def start_autotrade(self) -> None:
        """Navigate to 'Start Autotrade' via Main Menu to reduce /start spam.

        Handles three cases:
        1. On stake selection screen → click Main Menu to go back
        2. On Main Menu → click Start Autotrade directly
        3. Elsewhere → send /start as fallback

        Waits 2 seconds before clicking to allow UI to fully render.
        """
        await asyncio.sleep(2)

        # Check if we're on stake selection screen (stuck between direction and execution)
        # If so, click Main Menu to escape
        for msg_tuple in await self._recent(limit=5):
            msg, text, btns = msg_tuple
            if is_stake_selection_screen(text):
                log.debug("Detected stake selection screen — clicking Main Menu")
                if await self._click(lambda x: "main menu" in x.lower(), limit=8):
                    await asyncio.sleep(2)
                    break
                # If Main Menu not found, try /start
                break

        # Try to find Start Autotrade button directly (natural flow from Main Menu)
        for label in ("🚀 Start Autotrade", "Start Autotrade", "Start Trade"):
            if await self._click(lambda x, L=label: L in x):
                await asyncio.sleep(3)
                return

        # Fallback: send /start if button not found (e.g., connection reset)
        try:
            await self._c.send_message(self._bot, "/start")
        except FloodWaitError as e:
            wait = getattr(e, "seconds", 60) or 60
            log.warning("FloodWait on /start fallback — sleeping {}s", wait)
            await asyncio.sleep(wait)
            await self._c.send_message(self._bot, "/start")
        await asyncio.sleep(2.5)
        for label in ("🚀 Start Autotrade", "Start Autotrade", "Start Trade"):
            if await self._click(lambda x, L=label: L in x):
                await asyncio.sleep(3)
                return

    async def dismiss_nag_if_present(self) -> bool:
        if not self._click_anyway:
            return False
        for _ in range(3):
            t = await self._click(lambda x: "trade anyway" in x.lower(), limit=8)
            if t:
                await asyncio.sleep(2.5)
                return True
            await asyncio.sleep(1.0)
        return False

    async def select_pair(self, pair_api: str) -> bool:
        clicked = await self._click(lambda x: normalize_pair(x) == pair_api)
        if not clicked:
            return False
        await asyncio.sleep(2.5)
        await self.dismiss_nag_if_present()
        await asyncio.sleep(3)
        return True

    async def read_latest_text(self, limit=6) -> tuple[str, list[str]]:
        msgs = await self._recent(limit)
        if not msgs:
            return "", []
        _, text, btns = msgs[0]
        return text, btns

    async def wait_for_prediction(
        self, timeout: float = 60.0, interval: float = 2.0
    ) -> tuple[str, list[str]]:
        """Poll until the actionable Bot Prediction screen (with pair buttons) arrives.

        After 'Start Autotrade' the bot posts a 'Launched / AI analysis: Running'
        status and only produces the prediction screen several seconds later. We
        poll read_latest_text until we see a 'Bot Prediction' message that has
        pair buttons, dismissing any nag screen encountered along the way.

        Timeout is 60s by default to survive FloodWait delays (up to ~40s).

        Returns (text, buttons) of the prediction screen, or ("", []) on timeout.
        """
        import time

        deadline = time.monotonic() + timeout
        while True:
            text, btns = await self.read_latest_text()
            low = (text or "").lower()
            if "bot prediction" in low and btns:
                return text, btns
            if is_nag_screen(text, btns):
                await self.dismiss_nag_if_present()
            if time.monotonic() >= deadline:
                return "", []
            await asyncio.sleep(interval)

    async def back_to_menu(self) -> None:
        """Return to Main Menu via button click (no /start).

        The next cycle's start_autotrade() handles all recovery cases — if the
        Main Menu button is not found here (e.g. the next cycle already navigated
        away, or a stale inline keyboard), do nothing. Sending /start here would
        race with the next cycle and spam the bot.
        """
        clicked = await self._click(lambda x: "main menu" in x.lower())
        if clicked:
            log.debug("Clicked Main Menu — next cycle will navigate from here")
            await asyncio.sleep(1.5)
        else:
            log.debug("back_to_menu: Main Menu button not found — next cycle will recover")
