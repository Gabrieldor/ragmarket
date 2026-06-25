"""Local sound notifier, ported from D:\\Rag\\src\\sound_notifier.py -- plays beeps instead
of sending Discord messages. Uses Python's built-in ``winsound`` module (Windows only; no
extra deps). Drop-in replacement for DiscordNotifier; both take a db.models.WatchRule row.

Beep patterns
-------------
  Triggered    -- three ascending tones  (condition became true)
  Cleared      -- two descending tones   (condition no longer true)
  Price change -- two short equal tones  (price moved while still active)
  Critical     -- five rapid high tones  (fatal error, e.g. rate-limited)
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import winsound
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False
    logger.warning("winsound not available -- sound notifications will be silent")


def _beep(freq: int, duration: int) -> None:
    if _HAS_WINSOUND:
        winsound.Beep(freq, duration)


def _play_triggered() -> None:
    _beep(600, 150)
    _beep(800, 150)
    _beep(1000, 300)


def _play_cleared() -> None:
    _beep(900, 150)
    _beep(600, 300)


def _play_price_changed() -> None:
    _beep(750, 120)
    _beep(750, 120)


def _play_critical() -> None:
    for _ in range(5):
        _beep(1200, 100)


def _fmt(price: int) -> str:
    return f"{price:,}".replace(",", ".")


class SoundNotifier:
    """Drop-in replacement for DiscordNotifier that plays local beeps."""

    def __init__(self, user_mention: str = "") -> None:
        self.user_mention = user_mention

    async def start(self) -> None:
        logger.info("Sound notifier active (local_sound=true)")

    async def close(self) -> None:
        pass

    async def send_triggered(self, rule, price: int) -> None:
        logger.info("[TRIGGERED] %s -- price %s", rule.raw, _fmt(price))
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _play_triggered)

    async def send_cleared(self, rule) -> None:
        logger.info("[CLEARED] %s", rule.raw)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _play_cleared)

    async def send_price_changed(self, rule, old_price: Optional[int], new_price: int) -> None:
        direction = "up" if new_price > (old_price or 0) else "down"
        logger.info(
            "[PRICE CHANGE] %s -- %s -> %s (%s)",
            rule.raw, _fmt(old_price or 0), _fmt(new_price), direction,
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _play_price_changed)

    async def send_critical(self, message: str) -> None:
        logger.critical("CRITICAL: %s", message)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _play_critical)
