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

_NAG_MARKERS = ("tokens running low", "trade anyway")
_DIR_MARKERS = ("direction:", "select trade amount", "setup detected")


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
                        except Exception as e:
                            log.debug("click failed: %s", e)
        return None

    async def start_autotrade(self) -> None:
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
            t = await self._click(lambda x: "trade anyway" in x.lower() or "anyway" in x.lower(), limit=8)
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

    async def back_to_menu(self) -> None:
        await self._click(lambda x: "main menu" in x.lower())
        await asyncio.sleep(1)
        await self._c.send_message(self._bot, "/start")
        await asyncio.sleep(2)
