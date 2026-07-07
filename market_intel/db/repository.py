from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from db.models import (
    CollectorConfig,
    CollectorStatus,
    DailyStat,
    HourlyStat,
    ListingObservation,
    MapAlias,
    MapStat,
    NotificationEvent,
    NotificationSettings,
    SaleEvent,
    ScrapeRun,
    ShopLocation,
    SoldOutConfig,
    ScraperConfig,
    SoldOutEvent,
    TrackedItem,
    WatchRule,
)
from sales_inference import InferredSaleEvent, compute_sale_events
from settings import settings
from sold_out_inference import InferredSoldOutTrigger, compute_sold_out_triggers


# ── Tracked items ────────────────────────────────────────────────────────────

def list_tracked_items(session: Session, *, active_only: bool = False) -> list[TrackedItem]:
    stmt = select(TrackedItem)
    if active_only:
        stmt = stmt.where(TrackedItem.is_active.is_(True))
    return list(session.scalars(stmt))


def add_tracked_item(
    session: Session,
    *,
    item_name: str,
    server_name: str = "FREYA",
    store_type: str = "BUY",
    display_name: str | None = None,
    site_item_id: int | None = None,
    poll_interval_override: int | None = None,
) -> TrackedItem:
    item = TrackedItem(
        item_name=item_name,
        display_name=display_name or item_name,
        site_item_id=site_item_id,
        server_name=server_name,
        store_type=store_type,
        poll_interval_override=poll_interval_override,
    )
    session.add(item)
    session.flush()
    return item


def set_tracked_item_active(session: Session, item_id: int, is_active: bool) -> None:
    item = session.get(TrackedItem, item_id)
    if item is None:
        raise ValueError(f"Tracked item {item_id} not found")
    item.is_active = is_active
    item.updated_at = datetime.now()


def delete_tracked_item(session: Session, item_id: int) -> None:
    """Permanently removes a tracked item and everything derived from it:
    raw observations, hourly/daily/map rollups. Irreversible -- the caller
    (API layer) is responsible for getting explicit user confirmation first.
    Does not touch shop_locations, since that cache is shared across items.
    """
    item = session.get(TrackedItem, item_id)
    if item is None:
        raise ValueError(f"Tracked item {item_id} not found")

    session.execute(delete(ListingObservation).where(ListingObservation.tracked_item_id == item_id))
    session.execute(delete(HourlyStat).where(HourlyStat.tracked_item_id == item_id))
    session.execute(delete(DailyStat).where(DailyStat.tracked_item_id == item_id))
    session.execute(delete(MapStat).where(MapStat.tracked_item_id == item_id))
    session.execute(delete(SoldOutEvent).where(SoldOutEvent.tracked_item_id == item_id))
    session.delete(item)


# ── Scrape runs ───────────────────────────────────────────────────────────────

def start_scrape_run(session: Session) -> ScrapeRun:
    run = ScrapeRun(status="running")
    session.add(run)
    session.flush()
    return run


def finish_scrape_run(
    session: Session,
    run: ScrapeRun,
    *,
    items_attempted: int,
    items_succeeded: int,
    location_lookups_performed: int,
    status: str = "success",
    error_message: str | None = None,
) -> None:
    run.finished_at = datetime.now()
    run.status = status
    run.items_attempted = items_attempted
    run.items_succeeded = items_succeeded
    run.location_lookups_performed = location_lookups_performed
    run.error_message = error_message


# ── Shop location cache (ARCHITECTURE.md section 2) ───────────────────────────

def get_cached_shop_location(
    session: Session, *, seller_name: str, shop_name: str, server_name: str
) -> ShopLocation | None:
    stmt = select(ShopLocation).where(
        ShopLocation.seller_name == seller_name,
        ShopLocation.shop_name == shop_name,
        ShopLocation.server_name == server_name,
    )
    return session.scalars(stmt).first()


def upsert_shop_location(
    session: Session,
    *,
    seller_name: str,
    shop_name: str,
    server_name: str,
    map_id: int | None,
    map_name: str | None,
    x_pos: int | None,
    y_pos: int | None,
) -> ShopLocation:
    existing = get_cached_shop_location(
        session, seller_name=seller_name, shop_name=shop_name, server_name=server_name
    )
    now = datetime.now()
    if existing:
        existing.map_id = map_id
        existing.map_name = map_name
        existing.x_pos = x_pos
        existing.y_pos = y_pos
        existing.last_verified_at = now
        return existing

    location = ShopLocation(
        seller_name=seller_name,
        shop_name=shop_name,
        server_name=server_name,
        map_id=map_id,
        map_name=map_name,
        x_pos=x_pos,
        y_pos=y_pos,
        first_seen_at=now,
        last_verified_at=now,
    )
    session.add(location)
    session.flush()
    return location


# ── Observations ──────────────────────────────────────────────────────────────

def insert_observations(session: Session, observations: list[ListingObservation]) -> None:
    session.add_all(observations)
    session.flush()


# ── Collector status (single row, real-time state for the dashboard) ──────────

def get_collector_status(session: Session) -> CollectorStatus | None:
    return session.get(CollectorStatus, 1)


def set_collector_retry(session: Session) -> CollectorStatus:
    status = session.get(CollectorStatus, 1)
    if status is None:
        status = CollectorStatus(id=1)
        session.add(status)
    status.retry_requested = True
    session.flush()
    return status


def set_collector_paused(session: Session, paused: bool) -> CollectorStatus:
    status = session.get(CollectorStatus, 1)
    if status is None:
        status = CollectorStatus(id=1)
        session.add(status)
    status.paused = paused
    session.flush()
    return status


def set_collector_status(
    session: Session,
    *,
    state: str,
    current_item_name: str | None = None,
    next_cycle_at: datetime | None = None,
    next_item_at: datetime | None = None,
    consecutive_rate_limits: int | None = None,
) -> CollectorStatus:
    status = session.get(CollectorStatus, 1)
    if status is None:
        status = CollectorStatus(id=1)
        session.add(status)

    status.state = state
    status.current_item_name = current_item_name
    status.next_cycle_at = next_cycle_at
    status.next_item_at = next_item_at
    if consecutive_rate_limits is not None:
        status.consecutive_rate_limits = consecutive_rate_limits
    status.updated_at = datetime.now()
    session.flush()
    return status


# ── Sale events (persisted sales inference, for later validation against real data) ───────

def record_sale_events(session: Session, tracked_item_id: int, events: list[InferredSaleEvent]) -> int:
    """Persists newly-inferred sale events for one tracked item, skipping any that were
    already recorded (matched by (tracked_item_id, ssi, sale_attributed_at) -- the same
    listing-instant is never recorded twice even if this is called again later with the
    same underlying observations). Returns the count of newly-inserted rows.
    """
    if not events:
        return 0

    existing = set(
        session.execute(
            select(SaleEvent.ssi, SaleEvent.sale_attributed_at).where(
                SaleEvent.tracked_item_id == tracked_item_id
            )
        ).all()
    )

    new_rows = [
        SaleEvent(
            tracked_item_id=tracked_item_id,
            ssi=event.ssi,
            seller_name=event.seller_name,
            map_name=event.map_name,
            quantity_sold=event.quantity_sold,
            price=event.price,
            sale_attributed_at=event.sale_attributed_at,
            method=event.method,
            relisted_ssi=event.relisted_ssi,
            relisted_quantity=event.relisted_quantity,
        )
        for event in events
        if (event.ssi, event.sale_attributed_at) not in existing
    ]
    session.add_all(new_rows)
    session.flush()
    return len(new_rows)


def infer_and_persist_sales(session: Session, tracked_item_id: int) -> int:
    """Runs sale inference over a tracked item's full observation history and persists any
    newly-confirmed events. Safe to call repeatedly (e.g. once per scrape cycle) -- already
    recorded events are skipped automatically.
    """
    observations = list(
        session.scalars(
            select(ListingObservation).where(ListingObservation.tracked_item_id == tracked_item_id)
        )
    )
    events = compute_sale_events(observations)
    return record_sale_events(session, tracked_item_id, events)


# ── Low-stock ("sold out") detection -- see sold_out_inference.py ─────────────

def get_scraper_config(session: Session) -> ScraperConfig:
    config = session.get(ScraperConfig, 1)
    if config is None:
        config = ScraperConfig(id=1, updated_at=datetime.now())
        session.add(config)
        session.flush()
    return config


def get_collector_config(session: Session) -> CollectorConfig:
    config = session.get(CollectorConfig, 1)
    if config is None:
        config = CollectorConfig(id=1, updated_at=datetime.now())
        session.add(config)
        session.flush()
    return config


def update_collector_config(
    session: Session,
    poll_interval_seconds: int | None = None,
    item_delay_seconds: float | None = None,
    location_click_delay_seconds: float | None = None,
) -> CollectorConfig:
    config = get_collector_config(session)
    if poll_interval_seconds is not None:
        config.poll_interval_seconds = poll_interval_seconds
    if item_delay_seconds is not None:
        config.item_delay_seconds = item_delay_seconds
    if location_click_delay_seconds is not None:
        config.location_click_delay_seconds = location_click_delay_seconds
    return config


def get_sold_out_config(session: Session) -> SoldOutConfig:
    """Get-or-create the single global config row (id=1), mirrors set_collector_status's
    get-or-create pattern. Lives in the DB (not settings.py) so it's editable live from the
    dashboard's Settings page without an app restart.
    """
    config = session.get(SoldOutConfig, 1)
    if config is None:
        config = SoldOutConfig(id=1)
        session.add(config)
        session.flush()
    return config


def update_sold_out_config(
    session: Session,
    *,
    threshold_ratio: float | None = None,
    quiet_hours_start: str | None = None,
    quiet_hours_end: str | None = None,
    clear_quiet_hours: bool = False,
) -> SoldOutConfig:
    """Updates only the fields explicitly passed. ``clear_quiet_hours`` is a separate flag
    (rather than overloading None) so quiet hours can be deliberately disabled, since None
    on quiet_hours_start/end already means "leave unchanged" here.
    """
    config = get_sold_out_config(session)
    if threshold_ratio is not None:
        config.threshold_ratio = threshold_ratio
    if clear_quiet_hours:
        config.quiet_hours_start = None
        config.quiet_hours_end = None
    else:
        if quiet_hours_start is not None:
            config.quiet_hours_start = quiet_hours_start
        if quiet_hours_end is not None:
            config.quiet_hours_end = quiet_hours_end
    config.updated_at = datetime.now()
    session.flush()
    return config


def record_sold_out_events(
    session: Session, tracked_item_id: int, triggers: list[InferredSoldOutTrigger]
) -> int:
    """Persists newly-triggered low-stock events for one tracked item, skipping any ssi
    already recorded (matched by the (tracked_item_id, ssi) unique constraint -- one trigger
    per listing lifetime). Returns the count of newly-inserted rows.
    """
    if not triggers:
        return 0

    existing = set(
        session.execute(
            select(SoldOutEvent.ssi).where(SoldOutEvent.tracked_item_id == tracked_item_id)
        ).scalars()
    )

    config = get_sold_out_config(session)
    new_rows = [
        SoldOutEvent(
            tracked_item_id=tracked_item_id,
            ssi=trigger.ssi,
            seller_name=trigger.seller_name,
            shop_name=trigger.shop_name,
            map_name=trigger.map_name,
            baseline_quantity=trigger.baseline_quantity,
            quantity_at_trigger=trigger.quantity_at_trigger,
            threshold_ratio=config.threshold_ratio,
            triggered_at=trigger.triggered_at,
        )
        for trigger in triggers
        if trigger.ssi not in existing
    ]
    session.add_all(new_rows)
    session.flush()
    return len(new_rows)


def infer_and_persist_sold_out(session: Session, tracked_item_id: int) -> int:
    """Runs low-stock detection over a tracked item's full observation history, using the
    current global config, and persists any newly-confirmed triggers. Safe to call
    repeatedly -- already recorded events are skipped automatically. Caller is responsible
    for only calling this when the item's sold_out_enabled flag is set.
    """
    config = get_sold_out_config(session)
    observations = list(
        session.scalars(
            select(ListingObservation).where(ListingObservation.tracked_item_id == tracked_item_id)
        )
    )
    triggers = compute_sold_out_triggers(
        observations,
        threshold_ratio=config.threshold_ratio,
        quiet_hours_start=config.quiet_hours_start,
        quiet_hours_end=config.quiet_hours_end,
        # Quiet hours should only cover for actual collector downtime, not interfere with
        # a normal poll-to-poll comparison that merely happens to land on the clock during
        # that window (e.g. the PC stayed on all night) -- 2x the configured poll interval
        # gives headroom for ordinary jitter (item throttling, a transient rate-limit retry)
        # without mistaking it for an overnight gap.
        max_normal_gap_seconds=settings.poll_interval_seconds * 2,
    )
    return record_sold_out_events(session, tracked_item_id, triggers)


def list_sold_out_events(
    session: Session,
    *,
    tracked_item_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[SoldOutEvent]:
    stmt = select(SoldOutEvent).order_by(SoldOutEvent.triggered_at.desc())
    if tracked_item_id is not None:
        stmt = stmt.where(SoldOutEvent.tracked_item_id == tracked_item_id)
    stmt = stmt.offset(offset).limit(limit)
    return list(session.scalars(stmt))


def get_active_sold_out_counts(session: Session) -> dict[int, int]:
    """Counts, per tracked_item_id, how many persisted SoldOutEvent rows are for a listing
    (ssi) that is still present in that item's most recent observation cycle -- i.e. still
    visibly low-stock right now, not just low-stock at some point in the past. Used for the
    Overview page's badge.
    """
    latest_by_item = dict(
        session.execute(
            select(ListingObservation.tracked_item_id, func.max(ListingObservation.observed_at))
            .group_by(ListingObservation.tracked_item_id)
        ).all()
    )
    if not latest_by_item:
        return {}

    current_pairs: set[tuple[int, str]] = set()
    for tracked_item_id, latest_at in latest_by_item.items():
        ssis = session.execute(
            select(ListingObservation.ssi).where(
                ListingObservation.tracked_item_id == tracked_item_id,
                ListingObservation.observed_at == latest_at,
                ListingObservation.ssi.is_not(None),
            )
        ).scalars().all()
        current_pairs.update((tracked_item_id, ssi) for ssi in ssis)

    counts: dict[int, int] = defaultdict(int)
    for event in session.scalars(select(SoldOutEvent)):
        if (event.tracked_item_id, event.ssi) in current_pairs:
            counts[event.tracked_item_id] += 1
    return dict(counts)


def get_latest_observations(session: Session, tracked_item_id: int) -> list[ListingObservation]:
    """All ListingObservation rows from a tracked item's most recent scrape cycle
    (max ``observed_at``). Used by map-only watch rules (notifications/checker.py) to check
    price+map conditions against already-collected data instead of re-scraping live.
    """
    latest_at = session.scalar(
        select(func.max(ListingObservation.observed_at)).where(
            ListingObservation.tracked_item_id == tracked_item_id
        )
    )
    if latest_at is None:
        return []
    return list(
        session.scalars(
            select(ListingObservation).where(
                ListingObservation.tracked_item_id == tracked_item_id,
                ListingObservation.observed_at == latest_at,
            )
        )
    )


# ── Watch rules / notifications -- ported price watcher, see notifications/ ───

def list_watch_rules(session: Session, *, active_only: bool = False) -> list[WatchRule]:
    stmt = select(WatchRule).order_by(WatchRule.created_at)
    if active_only:
        stmt = stmt.where(WatchRule.is_active.is_(True))
    return list(session.scalars(stmt))


def add_watch_rule(
    session: Session, *, raw: str, item_name: str, operator: str, target_price: int,
    required_refine: int | None = None, required_slot: int | None = None,
    required_map: str | None = None, excluded_maps: str | None = None,
    required_min_qty: int | None = None,
) -> WatchRule:
    existing = session.scalar(select(WatchRule).where(WatchRule.raw == raw))
    if existing is not None:
        raise ValueError(f"Rule already exists: {raw!r}")
    rule = WatchRule(
        raw=raw, item_name=item_name, operator=operator, target_price=target_price,
        required_refine=required_refine, required_slot=required_slot,
        required_map=required_map, excluded_maps=excluded_maps,
        required_min_qty=required_min_qty,
    )
    session.add(rule)
    session.flush()
    return rule


def find_tracked_item_by_name(session: Session, item_name: str) -> TrackedItem | None:
    """Case-insensitive lookup of a TrackedItem by ``item_name`` or ``display_name``. Used
    to validate/resolve map-filtered watch rules, since map data is only ever collected for
    actively tracked items (see notifications/checker.py's map-only rule path).
    """
    needle = item_name.strip().lower()
    return session.scalar(
        select(TrackedItem).where(
            (func.lower(TrackedItem.item_name) == needle)
            | (func.lower(TrackedItem.display_name) == needle)
        )
    )


def set_watch_rule_active(session: Session, rule_id: int, is_active: bool) -> WatchRule:
    rule = session.get(WatchRule, rule_id)
    if rule is None:
        raise ValueError(f"Watch rule {rule_id} not found")
    rule.is_active = is_active
    rule.updated_at = datetime.now()
    session.flush()
    return rule


def delete_watch_rule(session: Session, rule_id: int) -> None:
    rule = session.get(WatchRule, rule_id)
    if rule is None:
        raise ValueError(f"Watch rule {rule_id} not found")
    session.execute(delete(NotificationEvent).where(NotificationEvent.watch_rule_id == rule_id))
    session.delete(rule)


def list_notification_events(
    session: Session,
    *,
    watch_rule_id: int | None = None,
    event_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[NotificationEvent]:
    stmt = select(NotificationEvent).order_by(NotificationEvent.created_at.desc())
    if watch_rule_id is not None:
        stmt = stmt.where(NotificationEvent.watch_rule_id == watch_rule_id)
    if event_type is not None:
        stmt = stmt.where(NotificationEvent.event_type == event_type)
    stmt = stmt.offset(offset).limit(limit)
    return list(session.scalars(stmt))


def get_notification_settings(session: Session) -> NotificationSettings:
    """Get-or-create the single global settings row (id=1), mirrors get_sold_out_config's
    get-or-create pattern. Lives in the DB (not settings.py) so it's editable live from the
    dashboard's Price Watcher settings section without an app restart.
    """
    config = session.get(NotificationSettings, 1)
    if config is None:
        config = NotificationSettings(id=1)
        session.add(config)
        session.flush()
    return config


def update_notification_settings(session: Session, **fields) -> NotificationSettings:
    """Updates only the fields explicitly passed (None values are treated as "leave
    unchanged" -- there is no field here where None is itself a meaningful value to set,
    unlike sold-out config's quiet hours).
    """
    config = get_notification_settings(session)
    for key, value in fields.items():
        if value is not None:
            setattr(config, key, value)
    config.updated_at = datetime.now()
    session.flush()
    return config


# ── Map aliases (group raw map_name values under one canonical display name) ──

def list_map_aliases(session: Session) -> list[MapAlias]:
    return list(session.scalars(select(MapAlias).order_by(MapAlias.canonical_name, MapAlias.raw_map_name)))


def add_map_alias(session: Session, *, raw_map_name: str, canonical_name: str) -> MapAlias:
    """Upserts by raw_map_name -- re-adding an already-aliased raw name simply re-points it
    at the new canonical_name instead of erroring, so regrouping is a single action.
    """
    existing = session.scalar(select(MapAlias).where(MapAlias.raw_map_name == raw_map_name))
    if existing is not None:
        existing.canonical_name = canonical_name
        session.flush()
        return existing
    alias = MapAlias(raw_map_name=raw_map_name, canonical_name=canonical_name)
    session.add(alias)
    session.flush()
    return alias


def delete_map_alias(session: Session, alias_id: int) -> None:
    alias = session.get(MapAlias, alias_id)
    if alias is None:
        raise ValueError(f"Map alias {alias_id} not found")
    session.delete(alias)


def get_map_alias_lookup(session: Session) -> dict[str, str]:
    """raw_map_name -> canonical_name, for resolving in the map analytics endpoints. A
    raw map_name with no alias resolves to itself (handled by the caller via dict.get).
    """
    return {a.raw_map_name: a.canonical_name for a in list_map_aliases(session)}
