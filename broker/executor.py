"""Trade execution with demo mode guards."""

from dataclasses import dataclass, field
from datetime import datetime

from config.settings import settings, TradeMode
from utils.logger import log, log_trade


@dataclass
class TradeResult:
    id: str
    direction: str
    amount: float
    expiry: int
    timestamp: datetime
    status: str  # "PENDING", "WIN", "LOSS", "ERROR"
    error: str = ""


class TradeExecutor:
    """Place trades via DOM interaction."""

    def __init__(self, page, scraper, dry_run: bool = True):
        self._page = page
        self._scraper = scraper
        self._dry_run = dry_run or settings.dry_run
        self._trade_counter = 0

    # ────────────────────────────────────────────────────────────────

    async def place_trade(self, direction: str, amount: float, expiry: int) -> TradeResult | None:
        """Place a trade with full demo mode guard.

        CRITICAL: This is the key safety function. It MUST verify demo mode
        unless TRADE_MODE=LIVE and user has confirmed.
        """

        # ─── DEMO MODE GUARD ───────────────────────────────────────

        # Always check demo status
        is_demo = await self._scraper.is_demo_mode()

        if settings.trade_mode == TradeMode.DEMO:
            if not is_demo:
                error_msg = "ERROR: TRADE_MODE=DEMO but page shows LIVE mode. Aborting trade."
                log.critical(error_msg)
                return TradeResult(
                    id=f"failed_{self._trade_counter}",
                    direction=direction,
                    amount=amount,
                    expiry=expiry,
                    timestamp=datetime.now(),
                    status="ERROR",
                    error=error_msg,
                )

        elif settings.trade_mode == TradeMode.LIVE:
            if is_demo:
                error_msg = "WARNING: TRADE_MODE=LIVE but page is in DEMO mode."
                log.warning(error_msg)
                # Don't block, but log it prominently
            else:
                log.critical(
                    "⚠️ LIVE TRADING ACTIVE ⚠️ Direction: %s | Amount: $%s",
                    direction,
                    amount,
                )

        # ─── DRY RUN MODE ──────────────────────────────────────────

        if self._dry_run:
            self._trade_counter += 1
            result = TradeResult(
                id=f"dry_run_{self._trade_counter}",
                direction=direction,
                amount=amount,
                expiry=expiry,
                timestamp=datetime.now(),
                status="PENDING",
            )
            log.info(f"[DRY RUN] Trade not placed: {result}")
            log_trade(result.__dict__)
            return result

        # ─── EXECUTE TRADE ────────────────────────────────────────

        self._trade_counter += 1
        try:
            # Find and click the button
            button_selector = "call" if direction == "CALL" else "put"
            button = await self._page.query_selector(
                f"[class*='{button_selector}'], [id*='{button_selector}']"
            )

            if not button:
                raise ValueError(f"Cannot find {direction} button")

            # Set amount (assumes an input field)
            amount_input = await self._page.query_selector("input[type='text']")
            if amount_input:
                await amount_input.fill(str(amount))
                await self._page.wait_for_timeout(200)

            # Click the button
            await button.click()
            await self._page.wait_for_timeout(500)

            # Verify trade was placed
            result_text = await self._scraper.last_trade_result()

            result = TradeResult(
                id=f"trade_{self._trade_counter}",
                direction=direction,
                amount=amount,
                expiry=expiry,
                timestamp=datetime.now(),
                status="PENDING" if result_text is None else result_text,
            )

            log.info(f"Trade executed: {result}")
            log_trade(result.__dict__)
            return result

        except Exception as e:
            error_result = TradeResult(
                id=f"failed_{self._trade_counter}",
                direction=direction,
                amount=amount,
                expiry=expiry,
                timestamp=datetime.now(),
                status="ERROR",
                error=str(e),
            )
            log.error(f"Trade execution failed: {e}")
            log_trade(error_result.__dict__)
            return error_result
