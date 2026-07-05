"""Watch-rule checking, ported from D:\\Rag\\src\\monitor.py -- replaces Monitor with two
pieces: a pure evaluate_rule() (directly ported from Monitor._evaluate/_bounds, fully
unit-testable) and an async check_watch_rules() that persists state instead of holding it
in an in-memory dict (db.models.WatchRule.state_active/last_price survive a collector
restart, unlike the original tool's RuleState).

Operator logic (ported verbatim)
---------------------------------
  ``<``  -- TRUE when the cheapest listing is at or below the target price (within
            variance). A good deal is available.
  ``>``  -- Behaviour depends on ``min_items_below``:
              0 (default): TRUE when even the cheapest listing is at or above the target
                price (within variance). The whole market is expensive.
              N (e.g. 100): TRUE when the total item quantity available below the target
                price drops below N. Supply is running low -- good time to sell.

RateLimitError is intentionally left uncaught here -- the collector decides what "stop
this cycle early" means for the merged watch-rule + tracked-item cycle (see
collector/runner.py).
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import NotificationEvent, NotificationSettings, WatchRule
from db.repository import find_tracked_item_by_name, get_latest_observations, get_map_alias_lookup
from scraper_adapter.location_action import parse_item_name_title

logger = logging.getLogger(__name__)


def _bounds(target_price: int, variance_percent: float) -> tuple[int, int]:
    """Return (lower_bound, upper_bound) after applying variance."""
    variance = target_price * (variance_percent / 100)
    return int(target_price - variance), int(target_price + variance)


def _canonical_map(map_name: str | None, alias_lookup_ci: dict[str, str]) -> str | None:
    """Resolves a raw map name to its canonical form (case-insensitively looked up in
    ``alias_lookup_ci``, which must already have lowercase keys), then lowercases the
    result so two differently-cased references to the same map compare equal.
    """
    if not map_name:
        return None
    return alias_lookup_ci.get(map_name.lower(), map_name).lower()


def _fetch_map_filtered_listings(
    rule: WatchRule,
    session: Session,
    alias_lookup_ci: dict[str, str],
) -> list:
    """Map-only rules (``required_map`` set, no refine/slot) never hit the live site --
    map data only exists in the DB for actively tracked items (populated by the regular
    tracked-item scrape cycle), so this reads the rule's resolved TrackedItem's most recent
    scrape run's observations instead, filtered down to the ones on the required map.
    """
    tracked_item = find_tracked_item_by_name(session, rule.item_name)
    if tracked_item is None:
        logger.warning(
            "[%s] required_map set but '%s' is no longer a tracked item -- skipping.",
            rule.raw, rule.item_name,
        )
        return []

    observations = get_latest_observations(session, tracked_item.id)
    target_map = _canonical_map(rule.required_map, alias_lookup_ci)
    return [
        obs for obs in observations
        if _canonical_map(obs.map_name, alias_lookup_ci) == target_map
    ]


def evaluate_rule(
    rule: WatchRule,
    listings: list,
    variance_percent: float,
    min_items_below: int,
) -> tuple[bool, Optional[int]]:
    """Check whether a watch rule's condition is satisfied.

    Returns:
        (condition_met, cheapest_price)

    The reported price is always the cheapest listing found, regardless of operator *and*
    regardless of whether the condition is met -- callers that only care about
    notification-worthy transitions can ignore it when condition_met is False, but the
    dashboard's "current price" display needs the real market price even when nothing has
    triggered yet.

    ``listings`` accepts anything with ``.price``/``.quantity`` attributes (e.g.
    data_provider.Listing or a plain test double).
    """
    if not listings:
        return False, None

    lower, upper = _bounds(rule.target_price, variance_percent)
    cheapest = min(l.price for l in listings)

    if rule.operator == '<':
        condition_met = cheapest <= upper
    elif min_items_below == 0:
        condition_met = cheapest >= lower
    else:
        supply_below = sum(l.quantity for l in listings if l.price < rule.target_price)
        logger.debug(
            "[%s] supply below %d: %d item(s) (threshold: %d)",
            rule.raw, rule.target_price, supply_below, min_items_below,
        )
        condition_met = supply_below < min_items_below

    return condition_met, cheapest


async def _fetch_refine_slot_matched_listings(
    rule: WatchRule,
    provider,
    config: NotificationSettings,
    alias_lookup_ci: dict[str, str],
) -> list:
    """Re-scrape ``rule``'s listings through their shop-location modal to verify the
    actual refine level / slot count, keeping only listings matching
    ``rule.required_refine``/``rule.required_slot``. Only called when at least one of
    those is set on the rule -- rules without them never pay this cost (see
    ``check_watch_rules``).

    If ``rule.required_map`` is also set, the modal's ``location.map_name`` (already being
    fetched anyway for the refine/slot check, so this is free) is canonicalized the same
    way and must match too, or the candidate is rejected.

    Requires ``provider.scrape_item()`` (``DetailedListingProvider`` -- carries
    ``dom_index`` so a matching card can be clicked). Candidates are limited to listings
    priced at or below the rule's upper variance bound, mirroring the price-threshold
    selection ``evaluate_rule`` already applies, so refine/slot verification doesn't have
    to open every card on the page -- only the ones that could plausibly matter.
    Throttling between modal clicks is handled inside ``scrape_item`` itself
    (``location_click_delay_seconds``), same as the tracked-item location lookups.
    """
    if not hasattr(provider, "scrape_item"):
        logger.warning(
            "[%s] required_refine/required_slot set but provider has no scrape_item() -- "
            "skipping refine/slot verification.", rule.raw,
        )
        return []

    _, upper = _bounds(rule.target_price, config.variance_percent)

    def _needs_check(listing) -> bool:
        return listing.price <= upper

    detailed = await provider.scrape_item(
        item_name=rule.item_name,
        store_type=config.store_type,
        server_type=config.server_type,
        needs_location=_needs_check,
        sort="LOW_PRICE",
        max_pages=config.max_pages,
    )

    matched = []
    for listing, location in detailed:
        if not _needs_check(listing):
            # Not a price candidate -- refine/slot was never looked up for it.
            continue
        if location is None or location.item_name_title is None:
            logger.debug(
                "[%s] could not verify refine/slot for a candidate listing -- skipping it.",
                rule.raw,
            )
            continue
        actual_refine, actual_slot = parse_item_name_title(location.item_name_title)
        if rule.required_refine is not None and actual_refine != rule.required_refine:
            continue
        if rule.required_slot is not None and actual_slot != rule.required_slot:
            continue
        if rule.required_map is not None:
            actual_map = _canonical_map(location.map_name, alias_lookup_ci)
            target_map = _canonical_map(rule.required_map, alias_lookup_ci)
            if actual_map != target_map:
                continue
        matched.append(listing)

    return matched


async def check_watch_rules(
    session: Session,
    provider,
    notifier,
    config: NotificationSettings,
) -> int:
    """Checks every active WatchRule sequentially (sleeping ``rule_delay_seconds`` between
    each, like the original tool's ``rule_delay``), firing notifications on state
    transitions only -- never re-notifies while a condition holds steady at the same price.
    Returns the count of notifications fired this call.
    """
    rules = list(session.scalars(select(WatchRule).where(WatchRule.is_active.is_(True))))
    fired = 0
    alias_lookup_ci = {raw.lower(): canonical for raw, canonical in get_map_alias_lookup(session).items()}

    for index, rule in enumerate(rules):
        if index > 0:
            await asyncio.sleep(config.rule_delay_seconds)

        map_only = (
            rule.required_map is not None
            and rule.required_refine is None
            and rule.required_slot is None
        )
        if map_only:
            listings = _fetch_map_filtered_listings(rule, session, alias_lookup_ci)
        elif rule.required_refine is not None or rule.required_slot is not None:
            listings = await _fetch_refine_slot_matched_listings(rule, provider, config, alias_lookup_ci)
        else:
            listings = await provider.get_listings(
                item_name=rule.item_name,
                store_type=config.store_type,
                server_type=config.server_type,
                sort="LOW_PRICE",
                max_pages=config.max_pages,
            )
        condition_met, best_price = evaluate_rule(
            rule, listings, config.variance_percent, config.min_items_below
        )
        rule.last_checked_price = best_price
        rule.last_checked_at = datetime.now()

        if condition_met and not rule.state_active:
            rule.state_active = True
            rule.last_price = best_price
            session.add(NotificationEvent(watch_rule_id=rule.id, event_type="triggered", price=best_price))
            await notifier.send_triggered(rule, best_price)
            fired += 1

        elif not condition_met and rule.state_active:
            old_price = rule.last_price
            rule.state_active = False
            rule.last_price = None
            session.add(
                NotificationEvent(watch_rule_id=rule.id, event_type="cleared", old_price=old_price)
            )
            await notifier.send_cleared(rule)
            fired += 1

        elif condition_met and rule.state_active and best_price != rule.last_price:
            old_price = rule.last_price
            rule.last_price = best_price
            session.add(
                NotificationEvent(
                    watch_rule_id=rule.id, event_type="price_changed",
                    price=best_price, old_price=old_price,
                )
            )
            await notifier.send_price_changed(rule, old_price, best_price)
            fired += 1

        # Commit per rule, not just flush -- this loop spans multiple slow network scrapes
        # and rule_delay_seconds sleeps (potentially minutes across several rules). Flushing
        # without committing leaves a write transaction open against the *entire shared*
        # SQLite file for that whole span, blocking every other writer (the API, the
        # tracked-item scrape phase) with "database is locked" until the loop finally
        # finishes -- committing here releases the write lock immediately after each rule
        # instead, mirroring the per-item commit pattern in collector/runner.py.
        session.commit()

    return fired
