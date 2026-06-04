#!/usr/bin/env python3
"""Generate a Telethon StringSession for use in cloud / headless environments.

Run this LOCALLY (on your own machine where you can receive the SMS/app code):

    pip install telethon
    python3 tools/gen_telegram_session.py

It will prompt for your phone number and the Telegram OTP, then print a
StringSession string.  Paste that string into your .env as:

    TELEGRAM_SESSION_STRING=<the string printed here>

The StringSession is a credential — keep it secret and never commit it.
"""

import asyncio
import sys


def main() -> None:
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError:
        print("ERROR: telethon is not installed.  Run: pip install telethon")
        sys.exit(1)

    print("=== Telegram StringSession Generator ===")
    print()
    api_id_raw = input("Enter your TELEGRAM_API_ID (from https://my.telegram.org): ").strip()
    api_hash = input("Enter your TELEGRAM_API_HASH: ").strip()

    if not api_id_raw.isdigit():
        print(f"ERROR: API_ID must be a number, got: {api_id_raw!r}")
        sys.exit(1)

    api_id = int(api_id_raw)

    async def _gen() -> None:
        async with TelegramClient(StringSession(), api_id, api_hash) as client:
            await client.start()
            session_str = client.session.save()
            print()
            print("=" * 60)
            print("SUCCESS — add this to your .env file:")
            print()
            print(f"TELEGRAM_SESSION_STRING={session_str}")
            print()
            print("=" * 60)
            print("Also set (if not already):")
            print(f"  TELEGRAM_API_ID={api_id}")
            print(f"  TELEGRAM_API_HASH={api_hash}")
            print()
            print("Keep this string secret — it is equivalent to your Telegram password.")

    asyncio.run(_gen())


if __name__ == "__main__":
    main()
