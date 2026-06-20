"""DOM scraping for live PocketOption data."""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

# ── CSS/XPath Selectors ────────────────────────────────────────────
# These are extracted to a top-level dict so they can be updated
# without touching the rest of the source code.
# LIVE SELECTORS from PocketOption (verified 2026-05-25)
SELECTORS = {
    # Main trading info
    "price": {
        "css": ".price-up, [class*='price-up'], [class*='info-icons__icon']",
        "xpath": "//span[contains(@class,'price-up')]",
        "js": """(() => {
            // Real PocketOption selector: info-icons__icon price-up
            const el = document.querySelector('.price-up')
                        || document.querySelector('[class*="price-up"]')
                        || document.querySelector('.info-icons__icon');
            return el ? el.textContent.trim() : null;
        })()"""
    },
    "timer": {
        "css": "[class*='timer'], [class*='countdown'], [class*='time'], .timer",
        "xpath": "//span[contains(@class,'timer') or contains(@class,'countdown')]",
        "js": """(() => {
            const el = document.querySelector('[class*="timer"]')
                        || document.querySelector('[class*="countdown"]')
                        || Array.from(document.querySelectorAll('span')).find(s => /\\d+:\\d+/.test(s.textContent));
            return el ? el.textContent.trim() : null;
        })()"""
    },
    "balance": {
        "css": ".balance-info-block, [class*='balance-info-block']",
        "xpath": "//span[contains(@class,'balance-info-block')]",
        "js": """(() => {
            // Real PocketOption selector: balance-info-block
            const el = document.querySelector('.balance-info-block')
                        || document.querySelector('[class*="balance-info-block"]');
            return el ? el.textContent.trim() : null;
        })()"""
    },
    "asset": {
        "css": ".balance-info-block__currency, [class*='currency']",
        "xpath": "//span[contains(@class,'balance-info-block__currency')]",
        "js": """(() => {
            // Real PocketOption selector: balance-info-block__currency
            const el = document.querySelector('.balance-info-block__currency')
                        || document.querySelector('[class*="currency"]');
            return el ? el.textContent.trim() : null;
        })()"""
    },
    "last_trade_result": {
        "css": "[class*='result'], [class*='status'], [class*='outcome']",
        "xpath": "//span[contains(@class,'result') or contains(@class,'outcome')]",
        "js": """(() => {
            const el = document.querySelector('[class*="result"]')
                        || document.querySelector('[class*="outcome"]');
            return el ? el.textContent.trim().toUpperCase() : null;
        })()"""
    },
    # Trade buttons - PocketOption uses js-react-call-put-wrap-chart-1
    "call_button": {
        "css": ".js-react-call-put-wrap-chart-1.chart-row-1, [class*='call'], button:contains('CALL')",
        "xpath": "//button[contains(@class,'chart-row-1')][1]",
        "js": """(() => {
            // Real PocketOption: js-react-call-put-wrap-chart-1 chart-row-1 (first one = CALL)
            const els = document.querySelectorAll('.js-react-call-put-wrap-chart-1');
            if (els.length > 0) {
                return { exists: true, clickable: !els[0].disabled, text: els[0].textContent.trim() };
            }
            const el = document.querySelector('[class*="call"]')
                        || Array.from(document.querySelectorAll('button')).find(b => b.textContent.toUpperCase().includes('CALL'));
            return el ? { exists: true, clickable: !el.disabled, text: el.textContent.trim() } : null;
        })()"""
    },
    "put_button": {
        "css": ".js-react-call-put-wrap-chart-1.chart-row-1:last-of-type, [class*='put'], button:contains('PUT')",
        "xpath": "//button[contains(@class,'chart-row-1')][2]",
        "js": """(() => {
            // Real PocketOption: js-react-call-put-wrap-chart-1 chart-row-1 (second one = PUT)
            const els = document.querySelectorAll('.js-react-call-put-wrap-chart-1');
            if (els.length > 1) {
                return { exists: true, clickable: !els[1].disabled, text: els[1].textContent.trim() };
            }
            const el = document.querySelector('[class*="put"]')
                        || Array.from(document.querySelectorAll('button')).find(b => b.textContent.toUpperCase().includes('PUT'));
            return el ? { exists: true, clickable: !el.disabled, text: el.textContent.trim() } : null;
        })()"""
    },
    # Demo mode indicator — only check account-type UI elements, not all DOM text
    "demo_mode": {
        "css": "[class*='demo'], [class*='practice'], [data-testid='demo-mode']",
        "js": """(() => {
            // Only check specific account-type indicators, never full DOM text scan
            if (document.querySelector('[data-testid="demo-mode"]')) return true;
            // Balance block with explicit "Demo" label (not just any text containing "demo")
            const balanceBlock = document.querySelector('.balance-info-block');
            if (balanceBlock) {
                const label = balanceBlock.querySelector('.balance-info-block__title, [class*="label"], [class*="type"]');
                if (label && /^demo$/i.test(label.textContent.trim())) return true;
            }
            // Account switcher / header badge
            const accountType = document.querySelector('[class*="account-type"], [class*="account__type"], [class*="badge--demo"]');
            if (accountType && /demo|practice/i.test(accountType.textContent)) return true;
            return false;
        })()"""
    },
}

# ── Data Types ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScrapedData:
    current_price: float | None
    countdown_timer: int | None
    account_balance: float | None
    current_asset: str | None
    last_trade_result: str | None
    is_demo_mode: bool

# ── Helper ─────────────────────────────────────────────────────────

_DECIMAL_RE = re.compile(r"[+-]?\d+[.,]?\d*")
_BALANCE_RE = re.compile(r"[\d,.]+(?:\s*[A-Z]{3})?")


def _extract_float(text: str) -> float | None:
    if not text:
        return None
    cleaned = re.sub(r"[^\d.,-]", "", text.replace(" ", ""))
    if not cleaned:
        return None
    try:
        # European format: 1.234,56 → last comma is decimal separator
        if "," in cleaned and "." in cleaned:
            if cleaned.rindex(",") > cleaned.rindex("."):
                # comma is decimal: 1.234,56
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                # dot is decimal: 1,234.56
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            # ambiguous: treat as decimal separator (European)
            cleaned = cleaned.replace(",", ".")
        return float(cleaned)
    except ValueError:
        return None


def _extract_int(text: str) -> int | None:
    # Handle MM:SS or M:SS timer format → convert to total seconds
    m = re.search(r"(\d+):(\d+)", text)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    match = re.search(r"\d+", text)
    if match:
        return int(match.group())
    return None


class PocketOptionScraper:
    """Scrape live data from the PocketOption page."""

    def __init__(self, page: "Page") -> None:
        self._page = page

    # ── Core Scraping ───────────────────────────────────────────────

    async def get_data(self) -> ScrapedData:
        """Return all scraped data points in one shot."""
        raw = await self._page.evaluate("""
            () => ({
                price: %s,
                timer: %s,
                balance: %s,
                asset: %s,
                last_result: %s,
                is_demo: %s
            })
        """ % (
            SELECTORS["price"]["js"],
            SELECTORS["timer"]["js"],
            SELECTORS["balance"]["js"],
            SELECTORS["asset"]["js"],
            SELECTORS["last_trade_result"]["js"],
            SELECTORS["demo_mode"]["js"],
        ))

        return ScrapedData(
            current_price=_extract_float(raw.get("price", "")),
            countdown_timer=_extract_int(raw.get("timer", "")),
            account_balance=_extract_float(raw.get("balance", "")),
            current_asset=raw.get("asset"),
            last_trade_result=raw.get("last_result"),
            is_demo_mode=bool(raw.get("is_demo", True)),
        )

    # ── Individual Fields (for selective polling) ───────────────────

    async def current_price(self) -> float | None:
        data = await self.get_data()
        return data.current_price

    async def countdown_timer(self) -> int | None:
        data = await self.get_data()
        return data.countdown_timer

    async def account_balance(self) -> float | None:
        data = await self.get_data()
        return data.account_balance

    async def current_asset(self) -> str | None:
        data = await self.get_data()
        return data.current_asset

    async def last_trade_result(self) -> str | None:
        data = await self.get_data()
        return data.last_trade_result

    async def is_demo_mode(self) -> bool:
        data = await self.get_data()
        return data.is_demo_mode

    # ── WebSocket Interception ─────────────────────────────────────

    async def intercept_websocket(self) -> list[dict]:
        """Capture WebSocket messages for raw price feed."""
        messages = []

        async def handle_ws(ws):
            if "pocketoption.com" in ws.url:
                messages.append({"type": "ws_open", "url": ws.url})
                ws.on("framesent", lambda payload: messages.append({"sent": payload}))
                ws.on("framereceived", lambda payload: messages.append({"received": payload}))

        self._page.on("websocket", handle_ws)
        return messages
