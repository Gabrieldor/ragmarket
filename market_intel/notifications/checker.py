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
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import NotificationEvent, NotificationSettings, WatchRule
from db.repository import find_tracked_item_by_name, get_latest_observations, get_map_alias_lookup
from scraper_adapter.location_action import ShopLocationDetail, parse_item_name_title

logger = logging.getLogger(__name__)


@dataclass
class RuleListing:
    """Normalizes the 3 different listing shapes this module deals with -- live
    ``DetailedListing`` (scraper_adapter.provider_adapter), DB ``ListingObservation`` rows,
    and refine/slot modal-verified ``(listing, location)`` pairs -- into one uniform type
    before calling ``evaluate_rule``, so location data flows through the same way regardless
    of which path fetched it.
    """

    price: int
    quantity: int
    map_name: str | None = None
    x_pos: int | None = None
    y_pos: int | None = None
    seller_name: str | None = None
    shop_name: str | None = None
    ssi: str | None = None


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
    excluded_set: set[str],
) -> list[RuleListing]:
    """Map-filtered rules (``required_map`` and/or ``excluded_maps`` set, no refine/slot)
    never hit the live site -- map data only exists in the DB for actively tracked items
    (populated by the regular tracked-item scrape cycle), so this reads the rule's resolved
    TrackedItem's most recent scrape run's observations instead, filtered down to the ones
    on the required map (if set) and not on an excluded map.
    """
    tracked_item = find_tracked_item_by_name(session, rule.item_name)
    if tracked_item is None:
        logger.warning(
            "[%s] required_map/excluded_maps set but '%s' is no longer a tracked item -- "
            "skipping.", rule.raw, rule.item_name,
        )
        return []

    observations = get_latest_observations(session, tracked_item.id)
    target_map = _canonical_map(rule.required_map, alias_lookup_ci) if rule.required_map else None
    canonical_excluded = {_canonical_map(m, alias_lookup_ci) for m in excluded_set}
    results = []
    for obs in observations:
        canonical = _canonical_map(obs.map_name, alias_lookup_ci)
        if target_map is not None and canonical != target_map:
            continue
        if canonical is not None and canonical in canonical_excluded:
            continue
        results.append(
            RuleListing(
                price=obs.price,
                quantity=obs.quantity,
                map_name=obs.map_name,
                x_pos=obs.x_pos,
                y_pos=obs.y_pos,
                seller_name=obs.seller_name,
                shop_name=obs.shop_name,
                ssi=obs.ssi,
            )
        )
    return results


def evaluate_rule(
    rule: WatchRule,
    listings: list[RuleListing],
    variance_percent: float,
    min_items_below: int,
) -> tuple[bool, Optional[RuleListing]]:
    """Check whether a watch rule's condition is satisfied.

    Returns:
        (condition_met, cheapest_listing)

    The reported listing is always the cheapest one found, regardless of operator *and*
    regardless of whether the condition is met -- callers that only care about
    notification-worthy transitions can ignore it when condition_met is False, but the
    dashboard's "current price" display needs the real market price even when nothing has
    triggered yet.

    ``listings`` is a list of ``RuleListing``.
    """
    if not listings:
        return False, None

    lower, upper = _bounds(rule.target_price, variance_percent)
    cheapest = min(listings, key=lambda l: l.price)

    if rule.operator == '<':
        condition_met = cheapest.price <= upper
        if condition_met and rule.required_min_qty is not None:
            supply_at_or_below = sum(l.quantity for l in listings if l.price <= upper)
            condition_met = supply_at_or_below >= rule.required_min_qty
    elif min_items_below == 0:
        condition_met = cheapest.price >= lower
    else:
        supply_below = sum(l.quantity for l in listings if l.price < rule.target_price)
        logger.debug(
            "[%s] supply below %d: %d item(s) (threshold: %d)",
            rule.raw, rule.target_price, supply_below, min_items_below,
        )
        condition_met = supply_below < min_items_below

    return condition_met, cheapest


async def _fetch_verified_listings(
    rule: WatchRule,
    provider,
    config: NotificationSettings,
    alias_lookup_ci: dict[str, str],
    excluded_set: set[str],
) -> list[RuleListing]:
    """Re-scrape ``rule``'s listings through their shop-location modal to verify the
    actual refine level / slot count and/or map, keeping only listings that satisfy every
    constraint the rule sets. Only called when at least one of required_refine/
    required_slot/required_map/excluded_maps is set on the rule -- rules without any of
    those never pay this cost (see ``check_watch_rules``). If refine/slot are both None,
    those checks simply no-op.

    Requires ``provider.scrape_item()`` (``DetailedListingProvider`` -- carries
    ``dom_index`` so a matching card can be clicked). Candidates are limited to listings
    priced at or below the rule's upper variance bound, mirroring the price-threshold
    selection ``evaluate_rule`` already applies, so verification doesn't have to open every
    card on the page -- only the ones that could plausibly matter. Throttling between modal
    clicks is handled inside ``scrape_item`` itself (``location_click_delay_seconds``), same
    as the tracked-item location lookups.
    """
    if not hasattr(provider, "scrape_item"):
        logger.warning(
            "[%s] required_refine/required_slot/required_map/excluded_maps set but "
            "provider has no scrape_item() -- skipping verification.", rule.raw,
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

    canonical_excluded = {_canonical_map(m, alias_lookup_ci) for m in excluded_set}
    needs_title = rule.required_refine is not None or rule.required_slot is not None

    matched: list[RuleListing] = []
    for listing, location in detailed:
        if not _needs_check(listing):
            # Not a price candidate -- location was never looked up for it.
            continue
        if location is None:
            logger.debug(
                "[%s] could not verify a candidate listing (no location) -- skipping it.",
                rule.raw,
            )
            continue
        if needs_title and location.item_name_title is None:
            logger.debug(
                "[%s] could not verify refine/slot for a candidate listing -- skipping it.",
                rule.raw,
            )
            continue
        if needs_title:
            actual_refine, actual_slot = parse_item_name_title(location.item_name_title)
            if rule.required_refine is not None and actual_refine != rule.required_refine:
                continue
            if rule.required_slot is not None and actual_slot != rule.required_slot:
                continue
        actual_map = _canonical_map(location.map_name, alias_lookup_ci)
        if rule.required_map is not None:
            target_map = _canonical_map(rule.required_map, alias_lookup_ci)
            if actual_map != target_map:
                continue
        if actual_map is not None and actual_map in canonical_excluded:
            continue
        matched.append(
            RuleListing(
                price=listing.price,
                quantity=listing.quantity,
                map_name=location.map_name,
                x_pos=location.x_pos,
                y_pos=location.y_pos,
                seller_name=location.seller_name or getattr(listing, "seller_name", None),
                shop_name=getattr(listing, "shop_name", None),
                ssi=getattr(listing, "ssi", None),
            )
        )

    return matched


async def _fetch_location_for_notification(
    rule: WatchRule,
    cheapest: RuleListing,
    provider,
    config: NotificationSettings,
) -> ShopLocationDetail | None:
    """Resolves a location for a plain-rule notification (Feature A) -- the plain-rule path
    never fetches location during the check itself (to avoid needless site load per cycle),
    so this does ONE targeted ``provider.scrape_item()`` call, matching the cheapest
    listing by ``ssi`` if available, else by exact price. Only paid at the moment of firing
    a notification (rare), not on every check cycle.
    """
    if not hasattr(provider, "scrape_item"):
        return None

    def _is_match(listing) -> bool:
        if cheapest.ssi is not None:
            return getattr(listing, "ssi", None) == cheapest.ssi
        return listing.price == cheapest.price

    detailed = await provider.scrape_item(
        item_name=rule.item_name,
        store_type=config.store_type,
        server_type=config.server_type,
        needs_location=_is_match,
        sort="LOW_PRICE",
        max_pages=config.max_pages,
    )

    for listing, location in detailed:
        if _is_match(listing) and location is not None:
            return location
    return None


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

        rule_excluded_set = set(rule.excluded_maps.split(",")) if rule.excluded_maps else set()
        global_excluded_set = (
            {m.strip().lower() for m in config.global_excluded_maps.split(",") if m.strip()}
            if config.global_excluded_maps
            else set()
        )
        excluded_set = rule_excluded_set | global_excluded_set
        needs_refine_slot = rule.required_refine is not None or rule.required_slot is not None
        needs_map = rule.required_map is not None or bool(excluded_set)

        if needs_refine_slot:
            listings = await _fetch_verified_listings(
                rule, provider, config, alias_lookup_ci, excluded_set
            )
        elif needs_map:
            tracked_item = find_tracked_item_by_name(session, rule.item_name)
            if tracked_item is not None:
                listings = _fetch_map_filtered_listings(rule, session, alias_lookup_ci, excluded_set)
            else:
                listings = await _fetch_verified_listings(
                    rule, provider, config, alias_lookup_ci, excluded_set
                )
        else:
            listings = [
                RuleListing(
                    price=l.price,
                    quantity=l.quantity,
                    seller_name=getattr(l, "seller_name", None),
                    shop_name=getattr(l, "shop_name", None),
                    ssi=getattr(l, "ssi", None),
                )
                for l in await provider.get_listings(
                    item_name=rule.item_name,
                    store_type=config.store_type,
                    server_type=config.server_type,
                    sort="LOW_PRICE",
                    max_pages=config.max_pages,
                )
            ]

        condition_met, cheapest = evaluate_rule(
            rule, listings, config.variance_percent, config.min_items_below
        )
        best_price = cheapest.price if cheapest else None
        rule.last_checked_price = best_price
        rule.last_checked_at = datetime.now()

        async def _resolve_location() -> ShopLocationDetail | None:
            """Location for the notification (Feature A) -- built directly from the
            cheapest listing if already known (map-only/verified-live paths), else fetched
            with one targeted live lookup (plain-rule path never fetches location during
            the check itself).
            """
            if cheapest is None:
                return None
            if cheapest.map_name is not None:
                return ShopLocationDetail(
                    map_name=cheapest.map_name, x_pos=cheapest.x_pos, y_pos=cheapest.y_pos,
                    seller_name=cheapest.seller_name, server_name=None,
                )
            return await _fetch_location_for_notification(rule, cheapest, provider, config)

        if condition_met and not rule.state_active:
            rule.state_active = True
            rule.last_price = best_price
            session.add(NotificationEvent(watch_rule_id=rule.id, event_type="triggered", price=best_price))
            location = await _resolve_location()
            await notifier.send_triggered(rule, best_price, location=location)
            fired += 1

        elif not condition_met and rule.state_active:
            # State still transitions and the event is still recorded (for the watcher
            # page's history/audit trail) -- only the Discord/sound notification itself is
            # skipped, since the user only wants to be alerted when a condition becomes
            # true, not when it stops being true.
            old_price = rule.last_price
            rule.state_active = False
            rule.last_price = None
            session.add(
                NotificationEvent(watch_rule_id=rule.id, event_type="cleared", old_price=old_price)
            )

        elif condition_met and rule.state_active and best_price != rule.last_price:
            old_price = rule.last_price
            rule.last_price = best_price
            session.add(
                NotificationEvent(
                    watch_rule_id=rule.id, event_type="price_changed",
                    price=best_price, old_price=old_price,
                )
            )
            location = await _resolve_location()
            await notifier.send_price_changed(rule, old_price, best_price, location=location)
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
