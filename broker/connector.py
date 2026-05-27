"""CDP connection manager via Playwright."""

import asyncio
from typing import Any

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from config.settings import settings

_DEFAULT_CDP_URL = "http://localhost:9222"
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds


class CDPConnector:
    """Manages a persistent Playwright connection over Chrome DevTools Protocol.

    Responsibilities
    --------------
    - Connect to a running Chrome instance (launched with --remote-debugging-port).
    - Find the PocketOption tab by URL.
    - Reconnect automatically on disconnect (exponential backoff).
    """

    def __init__(self, cdp_url: str | None = None) -> None:
        self._cdp_url = cdp_url or settings.cdp_url or _DEFAULT_CDP_URL
        self._playwright: Playwright | None = None
        self._browser: BrowserContext | None = None
        self._page: Page | None = None
        self._connected = False
        self._retries = 0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @property
    def page(self) -> Page:
        """Current active page. Raises if disconnected."""
        if self._page is None or self._page.is_closed():
            raise ConnectionError("No active PocketOption page. Call reconnect() first.")
        return self._page

    @property
    def is_connected(self) -> bool:
        """True if Playwright + page are alive."""
        return (
            self._playwright is not None
            and self._browser is not None
            and self._page is not None
            and not self._page.is_closed()
        )

    async def connect(self) -> Page:
        """Establish CDP connection and return the PocketOption page."""
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                self._page = await self._try_connect()
                self._connected = True
                self._retries = 0
                return self._page
            except ConnectionError:
                if attempt == _MAX_RETRIES:
                    raise
                wait = _BACKOFF_BASE * (2 ** (attempt - 1))
                await asyncio.sleep(wait)

        # Unreachable; satisfies type-checker.
        raise ConnectionError("Failed to connect after maximum retries.")

    async def reconnect(self) -> Page:
        """Force a fresh connection."""
        await self._disconnect()
        return await self.connect()

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    async def _try_connect(self) -> Page:
        self._playwright = await async_playwright().start()
        # connect_over_cdp expects a WebSocket or HTTP endpoint
        self._browser = await self._playwright.chromium.connect_over_cdp(self._cdp_url)
        target = await self._find_pocketoption_page()
        if target is None:
            await self._disconnect()
            raise ConnectionError("PocketOption page not found on CDP target list.")
        return target

    async def _find_pocketoption_page(self) -> Any | None:
        """Return the first page whose URL contains 'pocketoption.com'."""
        # browser.new_context() is not needed when using connect_over_cdp;
        # we work with the existing browser context.
        contexts = self._browser.contexts  # type: ignore[union-attr]
        for ctx in contexts:
            for pg in ctx.pages:
                if "pocketoption.com" in pg.url:
                    return pg
        return None

    async def _disconnect(self) -> None:
        self._connected = False
        if self._page and not self._page.is_closed():
            # Don't close the page (it's managed by Chrome), just drop the ref.
            self._page = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
