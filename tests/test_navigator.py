# tests/test_navigator.py
import pytest

from telegram_feed.navigator import (
    Navigator,
    find_pair_button_text,
    is_nag_screen,
    is_direction_screen,
)

def test_find_pair_button_among_menu_buttons():
    btns = ["⬅️ Main Menu", "🏆 AUD/USD OTC ≈78%", "CHF/JPY OTC ≈70%"]
    assert find_pair_button_text(btns, "AUDUSD_otc") == "🏆 AUD/USD OTC ≈78%"

def test_is_nag_screen():
    assert is_nag_screen("⚡ Tokens running low - you can trade anyway", ["🚀 Trade Anyway"]) is True
    assert is_nag_screen("📊 Bot Prediction", []) is False

def test_is_direction_screen():
    assert is_direction_screen("Direction: 🟢 BUY  Select trade amount") is True
    assert is_direction_screen("📊 Bot Prediction") is False


# ── async wait_for_prediction (timing fix) ──────────────────────────────────


class _FakeBtn:
    def __init__(self, text):
        self.text = text


class _FakeMsg:
    def __init__(self, text, button_texts=None, mid=1):
        self.text = text
        self.id = mid
        self.buttons = [[_FakeBtn(t) for t in button_texts]] if button_texts else None

    async def click(self, i, j):
        return None


class _FakeClient:
    """Returns a new message-state on each iter_messages() call (poll simulation)."""

    def __init__(self, states):
        self._states = states
        self._idx = 0

    def iter_messages(self, bot, limit=10):
        state = self._states[min(self._idx, len(self._states) - 1)]
        self._idx += 1

        async def gen():
            for m in state[:limit]:
                yield m

        return gen()

    async def send_message(self, *a, **k):
        return None


@pytest.mark.asyncio
async def test_wait_for_prediction_polls_until_buttons_appear():
    """The 'AI analysis: Running' status precedes the prediction by ~10s.
    wait_for_prediction must poll past the status until the actionable
    Bot Prediction screen (with pair buttons) arrives."""
    running = [_FakeMsg("🤖 POCKET ROBOT: Launched ✅\n📊AI analysis: Running")]
    prediction = [
        _FakeMsg(
            "📊 Bot Prediction:\n🏆 AUD/USD OTC: Win rate ≈79%",
            ["🏆 AUD/USD OTC", "EUR/RUB OTC", "⬅️ Main Menu"],
            mid=2,
        )
    ]
    client = _FakeClient([running, running, prediction])
    nav = Navigator(client, "po_broker_bot")

    text, btns = await nav.wait_for_prediction(timeout=10, interval=0.001)
    assert "bot prediction" in text.lower()
    assert "🏆 AUD/USD OTC" in btns


@pytest.mark.asyncio
async def test_wait_for_prediction_times_out_cleanly():
    """If the prediction never arrives, return empty (not hang/raise)."""
    running = [_FakeMsg("📊AI analysis: Running")]
    client = _FakeClient([running])
    nav = Navigator(client, "po_broker_bot")

    text, btns = await nav.wait_for_prediction(timeout=0.05, interval=0.001)
    assert text == ""
    assert btns == []
