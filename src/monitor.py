"""Core monitoring engine.

Rules are checked sequentially one at a time to avoid rate-limiting (429) from
the catalog site.  A configurable delay is inserted between each rule check.
After all rules have been checked the engine sleeps for ``poll_interval``
seconds before starting the next round.

State machine per rule
──────────────────────
  INITIAL  ──(condition met)──▶  TRUE   ──(price changes)──▶  TRUE  (notify)
     │                              │                            │
     │                              └──(condition clears)──▶  FALSE  (notify)
     │                                                           │
     └──(no match yet)──▶  FALSE  (silent)◀──────────────────────

Operator logic
──────────────
  ``<``  — TRUE when the cheapest listing is at or below the target price.
            (A good deal is available.)

  ``>``  — Behaviour depends on ``min_items_below`` in config.json:

           min_items_below = 0  (default)
               TRUE when the cheapest listing is at or above the target price.
               (The whole market is expensive.)

           min_items_below = N  (e.g. 100)
               TRUE when the total item quantity available below the target
               price drops below N.
               (Supply is running low — good time to sell.)
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from data_provider import DataProvider, Listing
from discord_notifier import DiscordNotifier
from parser import WatchRule
from playwright_provider import RateLimitError

logger = logging.getLogger(__name__)


def _fmt(price: int) -> str:
    return f"{price:,}".replace(",", ".")


@dataclass
class RuleState:
    rule: WatchRule
    active: bool = False
    last_price: Optional[int] = None


class Monitor:
    def __init__(
        self,
        provider: DataProvider,
        notifier: DiscordNotifier,
        config: dict,
    ) -> None:
        self.provider = provider
        self.notifier = notifier
        self.poll_interval: int = int(config.get("poll_interval", 60))
        self.rule_delay: float = float(config.get("rule_delay", 5))
        self.variance_percent: float = float(config.get("variance_percent", 1.0))
        self.store_type: str = config.get("store_type", "BUY")
        self.server_type: str = config.get("server_type", "FREYA")
        self.max_pages: int = int(config.get("max_pages", 1))
        self.min_items_below: int = int(config.get("min_items_below", 0))

    # ── Variance helpers ──────────────────────────────────────────────────────

    def _bounds(self, rule: WatchRule) -> tuple[int, int]:
        """Return (lower_bound, upper_bound) after applying variance."""
        variance = rule.target_price * (self.variance_percent / 100)
        return int(rule.target_price - variance), int(rule.target_price + variance)

    # ── Condition evaluation ──────────────────────────────────────────────────

    def _evaluate(
        self, rule: WatchRule, listings: list[Listing]
    ) -> tuple[bool, Optional[int]]:
        """Check whether the rule condition is satisfied.

        Returns:
            (condition_met, reported_price)

        The reported price is always the cheapest listing found, regardless of
        operator, so the user always knows the current best available price.
        """
        if not listings:
            return False, None

        lower, upper = self._bounds(rule)
        cheapest = min(l.price for l in listings)

        if rule.operator == '<':
            # TRUE when a listing exists at or below the upper bound.
            return (True, cheapest) if cheapest <= upper else (False, None)

        # operator == '>'
        if self.min_items_below == 0:
            # Default: TRUE when even the cheapest listing is above the lower bound.
            return (True, cheapest) if cheapest >= lower else (False, None)

        # Supply mode: TRUE when total quantity available below target < min_items_below.
        supply_below = sum(l.quantity for l in listings if l.price < rule.target_price)
        logger.debug(
            "[%s] supply below %d: %d item(s) (threshold: %d)",
            rule.raw, rule.target_price, supply_below, self.min_items_below,
        )
        return (True, cheapest) if supply_below < self.min_items_below else (False, None)

    def _sort_for(self, _rule: WatchRule) -> str:
        """Always sort lowest-price-first so cheapest listings land on page 1."""
        return "LOW_PRICE"

    # ── Console helpers ───────────────────────────────────────────────────────

    def _rule_summary(self, state: RuleState, listings: list[Listing], condition_met: bool, best_price: Optional[int]) -> str:
        rule = state.rule
        if not listings:
            return "  no listings found"

        cheapest = min(l.price for l in listings)
        parts = [f"  cheapest: {_fmt(cheapest)}"]

        if self.min_items_below > 0 and rule.operator == '>':
            supply = sum(l.quantity for l in listings if l.price < rule.target_price)
            parts.append(f"supply below {_fmt(rule.target_price)}: {supply} items (threshold: {self.min_items_below})")

        if condition_met:
            status = "TRIGGERED 🚨" if not state.active else "still active ✓"
        else:
            status = "cleared ✅" if state.active else "not met"
        parts.append(status)

        return "  " + " | ".join(parts)

    # ── Single-rule check ─────────────────────────────────────────────────────

    async def _check_rule(self, state: RuleState) -> None:
        """Fetch listings for one rule and fire notifications if state changed."""
        rule = state.rule
        listings = await self.provider.get_listings(
            item_name=rule.item_name,
            store_type=self.store_type,
            server_type=self.server_type,
            sort=self._sort_for(rule),
            max_pages=self.max_pages,
        )

        condition_met, best_price = self._evaluate(rule, listings)
        print(self._rule_summary(state, listings, condition_met, best_price))

        if condition_met and not state.active:
            state.active = True
            state.last_price = best_price
            await self.notifier.send_triggered(rule, best_price)

        elif not condition_met and state.active:
            state.active = False
            state.last_price = None
            await self.notifier.send_cleared(rule)

        elif condition_met and state.active and best_price != state.last_price:
            old = state.last_price
            state.last_price = best_price
            await self.notifier.send_price_changed(rule, old, best_price)

    # ── Entry point ───────────────────────────────────────────────────────────

    async def run(self, load_rules: Callable[[], list[WatchRule]]) -> None:
        """Check all rules sequentially, sleep between them, then repeat.

        ``load_rules`` is called at the start of every loop so edits to
        watches.json (additions, removals) take effect on the next cycle
        without restarting the monitor.  State (active/last_price) is kept
        for rules that are still present; removed rules drop their state.
        """
        states: dict[str, RuleState] = {}
        loop_count = 0

        while True:
            loop_count += 1

            rules = load_rules()
            states = {
                rule.raw: states.get(rule.raw, RuleState(rule=rule))
                for rule in rules
            }
            state_list = list(states.values())

            now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            print(f"\n{'─' * 48}")
            print(f"  Loop #{loop_count}  —  {now}")
            print(f"{'─' * 48}")

            if not state_list:
                print("  No watch rules configured. Edit watches.json to add some.")
                print(f"\n  Next loop in {self.poll_interval}s…")
                await asyncio.sleep(self.poll_interval)
                continue

            for i, state in enumerate(state_list):
                print(f"  [{i + 1}/{len(state_list)}] {state.rule.raw}")
                try:
                    await self._check_rule(state)
                except RateLimitError:
                    print("  ⛔ Rate limited (429) — stopping.")
                    msg = (
                        f"{self.notifier.user_mention}\n\n"
                        "⛔ **Market Watcher stopped.**\n\n"
                        "The catalog returned **HTTP 429 (Too Many Requests)**.\n"
                        "Increase `rule_delay` / `page_delay` in config.json and restart."
                    )
                    await self.notifier.send_critical(msg)
                    sys.exit(1)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Unexpected error checking rule '%s'", state.rule.raw)
                    print("  ⚠ error — check logs")

                if i < len(state_list) - 1:
                    await asyncio.sleep(self.rule_delay)

            print(f"\n  All rules checked. Next loop in {self.poll_interval}s…")
            await asyncio.sleep(self.poll_interval)
