"""Diagnostic: drive po_broker_bot and dump raw screens (text + buttons).

Read-only navigation — clicks /start and Start Autotrade only, never an
amount button. Prints what the bot actually returns so we can calibrate the
prediction/direction parsers against the live format.

    python3 tools/v2_capture.py
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from config.settings import settings  # noqa: E402
from utils.logger import log, setup_logger  # noqa: E402

setup_logger(_ROOT)


async def main() -> None:
    from telethon import TelegramClient

    from telegram_feed.navigator import Navigator
    from telegram_feed.prediction_parser import parse_prediction

    client = TelegramClient(
        settings.telegram_session,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    async with client:
        nav = Navigator(client, settings.signal_bot_username, settings.click_trade_anyway)

        async def dump(tag: str, limit=5):
            print(f"\n=== {tag}: last {limit} messages (most recent first) ===")
            msgs = await nav._recent(limit=limit)
            for idx, (m, text, btns) in enumerate(msgs):
                print(f"\n--- [{idx}] id={m.id} ---")
                print("TEXT:", repr(text)[:300])
                print("BUTTONS:", btns)
                if idx == 0:
                    print("parse_prediction →", parse_prediction(text))
            return msgs

        # 1. Fresh /start — what does the MAIN MENU offer?
        print("=== sending /start (main menu) ===")
        await client.send_message(settings.signal_bot_username, "/start")
        await asyncio.sleep(3)
        await dump("main menu", limit=3)

        # 2. Start Autotrade + dismiss nag
        print("\n=== Start Autotrade ===")
        await nav.start_autotrade()
        await nav.dismiss_nag_if_present()

        # 3. Wait for a market scan / setup screen to arrive (predictions cost a token)
        for wait in (5, 10, 15):
            print(f"\n=== waiting {wait}s for a setup/prediction to arrive… ===")
            await asyncio.sleep(wait)
            msgs = await dump(f"after +{wait}s", limit=3)
            top_text = msgs[0][1] if msgs else ""
            if parse_prediction(top_text) or "setup detected" in top_text.lower():
                print("\n>>> Got a prediction/setup screen!")
                break


if __name__ == "__main__":
    asyncio.run(main())
