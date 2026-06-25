"""Discord notifier, ported from D:\\Rag\\src\\discord_notifier.py -- adapted to take a
db.models.WatchRule row directly (it already exposes .item_name/.operator/.target_price/.raw,
the same attributes the original read off its own parser.WatchRule dataclass) instead of
importing that dataclass.
"""

import asyncio
import logging
from typing import Optional

import discord

logger = logging.getLogger(__name__)


def _fmt(price: int) -> str:
    """Format an integer price with dot thousands separators (Portuguese style)."""
    return f"{price:,}".replace(",", ".")


class DiscordNotifier:
    """Sends watch-rule notifications to a Discord channel via a bot token.

    Messages are queued internally so that the checker never blocks waiting for Discord's
    rate-limiter. The discord.Client runs as a background asyncio task sharing the same
    event loop as the collector.
    """

    def __init__(self, token: str, channel_id: int, user_mention: str) -> None:
        self.token = token
        self.channel_id = channel_id
        self.user_mention = user_mention

        intents = discord.Intents.default()
        self._client = discord.Client(intents=intents)
        self._channel: Optional[discord.abc.Messageable] = None
        self._ready = asyncio.Event()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []

        @self._client.event
        async def on_ready() -> None:
            logger.info("Discord bot connected as %s", self._client.user)
            self._channel = self._client.get_channel(self.channel_id)
            if self._channel is None:
                try:
                    self._channel = await self._client.fetch_channel(self.channel_id)
                except discord.DiscordException as exc:
                    logger.error("Cannot fetch channel %d: %s", self.channel_id, exc)
            self._ready.set()

        @self._client.event
        async def on_disconnect() -> None:
            logger.warning("Discord bot disconnected")

    async def start(self) -> None:
        """Start the Discord client and queue-processor as background tasks."""
        self._tasks.append(asyncio.create_task(self._client.start(self.token), name="discord-client"))
        self._tasks.append(asyncio.create_task(self._process_queue(), name="discord-queue"))
        logger.info("Discord notifier starting...")

    async def _process_queue(self) -> None:
        """Drain the message queue, respecting Discord rate limits."""
        await self._ready.wait()
        while True:
            try:
                message = await self._queue.get()
                if self._channel is None:
                    logger.warning("Discord channel not set -- dropping message")
                    self._queue.task_done()
                    continue
                try:
                    await self._channel.send(message)
                    logger.debug("Discord message sent")
                except discord.HTTPException as exc:
                    if exc.status == 429:
                        retry_after = exc.retry_after if hasattr(exc, "retry_after") else 5.0
                        logger.warning("Discord rate-limited -- retrying in %.1fs", retry_after)
                        await asyncio.sleep(retry_after)
                        await self._channel.send(message)
                    else:
                        logger.error("Discord HTTP error: %s", exc)
                except discord.DiscordException as exc:
                    logger.error("Failed to send Discord message: %s", exc)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                return

    # -- Public helpers --------------------------------------------------------------

    def _condition_line(self, rule) -> str:
        symbol = ">=" if rule.operator == ">" else "<="
        return f"{rule.item_name} {symbol} {_fmt(rule.target_price)}"

    async def send_triggered(self, rule, price: int) -> None:
        msg = (
            f"{self.user_mention}\n\n"
            f"🚨 **{rule.item_name}** condition triggered.\n\n"
            f"**Condition:**\n{self._condition_line(rule)}\n\n"
            f"**Matching price:**\n{_fmt(price)}"
        )
        await self._queue.put(msg)
        logger.info("[TRIGGERED] %s -- price %s", rule.raw, _fmt(price))

    async def send_cleared(self, rule) -> None:
        msg = (
            f"{self.user_mention}\n\n"
            f"✅ **{rule.item_name}** condition is no longer true.\n\n"
            f"**Condition:**\n{self._condition_line(rule)}"
        )
        await self._queue.put(msg)
        logger.info("[CLEARED] %s", rule.raw)

    async def send_price_changed(self, rule, old_price: Optional[int], new_price: int) -> None:
        direction = "📈" if new_price > (old_price or 0) else "📉"
        msg = (
            f"{self.user_mention}\n\n"
            f"{direction} **{rule.item_name}** price changed.\n\n"
            f"**Previous:**\n{_fmt(old_price) if old_price is not None else 'N/A'}\n\n"
            f"**Current:**\n{_fmt(new_price)}"
        )
        await self._queue.put(msg)
        logger.info("[PRICE CHANGE] %s -- %s -> %s", rule.raw, _fmt(old_price or 0), _fmt(new_price))

    async def send_critical(self, message: str) -> None:
        """Send a message immediately, bypassing the queue. Used for fatal errors."""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=10.0)
            if self._channel:
                await self._channel.send(message)
        except Exception as exc:
            logger.error("Failed to send critical Discord message: %s", exc)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        try:
            await self._client.close()
        except Exception:
            pass
