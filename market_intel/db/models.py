from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# All timestamps in this codebase use datetime.now() (the system's local time), not UTC.
# This machine's local time is UTC-3 with no DST, so this matches the user's wall clock
# directly -- deliberately not "real" UTC. Every comparison against "now" (rate-limit grace
# windows, the 24h my-sales window, etc.) must use the same datetime.now() convention, or
# the time-window math silently breaks by the offset between local time and UTC.


class Base(DeclarativeBase):
    pass


class TrackedItem(Base):
    __tablename__ = "tracked_items"
    __table_args__ = (
        UniqueConstraint("item_name", "server_name", "store_type", name="uq_tracked_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    site_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    server_name: Mapped[str] = mapped_column(String, nullable=False, default="FREYA")
    store_type: Mapped[str] = mapped_column(String, nullable=False, default="BUY")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    poll_interval_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-item opt-out for low-stock ("sold out") detection -- some items churn too fast or
    # too slow for the global threshold/quiet-hours config to make sense for them.
    sold_out_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    observations: Mapped[list["ListingObservation"]] = relationship(back_populates="tracked_item")


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    items_attempted: Mapped[int] = mapped_column(Integer, default=0)
    items_succeeded: Mapped[int] = mapped_column(Integer, default=0)
    location_lookups_performed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    observations: Mapped[list["ListingObservation"]] = relationship(back_populates="scrape_run")


class ShopLocation(Base):
    """Cache of (seller, shop) -> map/position, per ARCHITECTURE.md section 2."""

    __tablename__ = "shop_locations"
    __table_args__ = (
        UniqueConstraint("seller_name", "shop_name", "server_name", name="uq_shop_location"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    seller_name: Mapped[str] = mapped_column(String, nullable=False)
    shop_name: Mapped[str] = mapped_column(String, nullable=False)
    server_name: Mapped[str] = mapped_column(String, nullable=False)
    # Numeric site ids (svrId/mapId) are only obtainable via the Server Action JSON, which the
    # UI-click method (the canonical approach, see ARCHITECTURE.md section 1) does not surface.
    # Left nullable for a possible future static map_name -> map_id lookup table.
    map_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    map_name: Mapped[str | None] = mapped_column(String, nullable=True)
    x_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_verified_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ListingObservation(Base):
    """Append-only fact table -- one row per listing per scrape cycle."""

    __tablename__ = "listings_observations"
    __table_args__ = (
        Index("ix_observations_item_time", "tracked_item_id", "observed_at"),
        Index("ix_observations_ssi", "ssi"),
        Index("ix_observations_map", "map_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    ssi: Mapped[str | None] = mapped_column(String, nullable=True)
    item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    seller_name: Mapped[str | None] = mapped_column(String, nullable=True)
    shop_name: Mapped[str | None] = mapped_column(String, nullable=True)
    server_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    server_name: Mapped[str | None] = mapped_column(String, nullable=True)
    store_type: Mapped[str | None] = mapped_column(String, nullable=True)

    map_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    map_name: Mapped[str | None] = mapped_column(String, nullable=True)
    x_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    y_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_source: Mapped[str | None] = mapped_column(String, nullable=True)  # 'cache' | 'fresh_lookup'

    page_num: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_on_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_outlier: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    tracked_item: Mapped["TrackedItem"] = relationship(back_populates="observations")
    scrape_run: Mapped["ScrapeRun"] = relationship(back_populates="observations")


class HourlyStat(Base):
    """Rollup, rebuildable from listings_observations -- not authoritative."""

    __tablename__ = "hourly_stats"
    __table_args__ = (
        UniqueConstraint("tracked_item_id", "date", "hour", name="uq_hourly_stat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)  # ISO date, e.g. "2026-06-23"
    hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23

    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    median_price: Mapped[float] = mapped_column(Float, nullable=False)
    min_price: Mapped[int] = mapped_column(Integer, nullable=False)
    max_price: Mapped[int] = mapped_column(Integer, nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    listing_count: Mapped[int] = mapped_column(Integer, nullable=False)


class DailyStat(Base):
    """Rollup, rebuildable from listings_observations -- not authoritative."""

    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint("tracked_item_id", "date", name="uq_daily_stat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    date: Mapped[str] = mapped_column(String, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday ... 6=Sunday
    is_weekend: Mapped[bool] = mapped_column(Boolean, nullable=False)

    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    median_price: Mapped[float] = mapped_column(Float, nullable=False)
    min_price: Mapped[int] = mapped_column(Integer, nullable=False)
    max_price: Mapped[int] = mapped_column(Integer, nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    listing_count: Mapped[int] = mapped_column(Integer, nullable=False)


class MapStat(Base):
    """Rollup, rebuildable from listings_observations -- not authoritative."""

    __tablename__ = "map_stats"
    __table_args__ = (
        UniqueConstraint(
            "tracked_item_id", "map_name", "period_start", "period_end", name="uq_map_stat"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    # Only the human-readable map name is captured (see ShopLocation note above); map_id stays
    # nullable for a possible future static lookup table.
    map_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    map_name: Mapped[str | None] = mapped_column(String, nullable=True)
    period_start: Mapped[str] = mapped_column(String, nullable=False)
    period_end: Mapped[str] = mapped_column(String, nullable=False)

    avg_price: Mapped[float] = mapped_column(Float, nullable=False)
    listing_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Population stddev of price within this rollup row's own period (one day, pre-aggregation).
    # The API layer combines these across a date range with the pooled-variance formula rather
    # than averaging them, since stddevs of different-sized groups don't average meaningfully.
    stddev_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class CollectorStatus(Base):
    """Single-row table the collector updates in real time so the dashboard can show
    what it's doing right now (scraping / sleeping / rate-limited), not just history.
    """

    __tablename__ = "collector_status"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    state: Mapped[str] = mapped_column(String, nullable=False, default="starting")
    # 'starting' | 'scraping' | 'sleeping' | 'rate_limited'
    current_item_name: Mapped[str | None] = mapped_column(String, nullable=True)
    next_cycle_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_item_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consecutive_rate_limits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class SoldOutConfig(Base):
    """Single-row table (like CollectorStatus) holding the global low-stock detection
    settings, editable live from the dashboard's Settings page -- deliberately not in
    settings.py/.env, since that would require an app restart to take effect.
    """

    __tablename__ = "sold_out_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    threshold_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.10)
    # "HH:MM" strings; either may be null to disable quiet-hours suppression entirely.
    # Supports overnight wraparound (e.g. start="23:00", end="06:00").
    quiet_hours_start: Mapped[str | None] = mapped_column(String, nullable=True, default="00:00")
    quiet_hours_end: Mapped[str | None] = mapped_column(String, nullable=True, default="06:00")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class ScraperConfig(Base):
    """Single-row table holding scraper-level behavior settings editable live from
    the dashboard without an app restart.
    """

    __tablename__ = "scraper_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    outlier_factor: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class CollectorConfig(Base):
    """Single-row table holding collector poll-timing settings editable live from
    the dashboard without an app restart.
    """

    __tablename__ = "collector_config"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    item_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=15.0)
    location_click_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class SoldOutEvent(Base):
    """A persisted, audit-able record of one listing crossing the low-stock threshold
    (see sold_out_inference.py for the detection method). One row per listing lifetime --
    quantities on a single listing (ssi) only ever decrease in this game's vending model,
    so a listing is never re-armed; a restock shows up as a brand new ssi with its own
    fresh baseline instead.
    """

    __tablename__ = "sold_out_events"
    __table_args__ = (
        UniqueConstraint("tracked_item_id", "ssi", name="uq_sold_out_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    ssi: Mapped[str] = mapped_column(String, nullable=False)
    seller_name: Mapped[str | None] = mapped_column(String, nullable=True)
    shop_name: Mapped[str | None] = mapped_column(String, nullable=True)
    map_name: Mapped[str | None] = mapped_column(String, nullable=True)
    baseline_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_at_trigger: Mapped[int] = mapped_column(Integer, nullable=False)
    # Snapshot of the global ratio at trigger time, so a later config change doesn't
    # retroactively change the meaning of past events.
    threshold_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class SaleEvent(Base):
    """A persisted, audit-able record of one inferred sale (see sales_inference.py for the
    detection method and its caveats). Recorded once confirmed -- not recomputed live on
    every request -- specifically so the inference method itself can be validated later
    against real data, rather than only ever existing as an ephemeral number.
    """

    __tablename__ = "sale_events"
    __table_args__ = (
        UniqueConstraint("tracked_item_id", "ssi", "sale_attributed_at", name="uq_sale_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    ssi: Mapped[str] = mapped_column(String, nullable=False)
    seller_name: Mapped[str | None] = mapped_column(String, nullable=True)
    map_name: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sale_attributed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    # 'decrease' | 'sellout_no_relist' | 'sellout_partial_relist'
    relisted_ssi: Mapped[str | None] = mapped_column(String, nullable=True)
    relisted_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class VendorAlias(Base):
    """A seller_name registered as belonging to the user. Multiple aliases (alts) all
    compile into one combined "my sales" view -- see MyListingSession.
    """

    __tablename__ = "vendor_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias_name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ItemCostBasis(Base):
    """Versioned cost-per-unit for a tracked item. Updating the cost adds a new row rather
    than overwriting the old one, so a sale's profit is computed from whatever the cost was
    *at the time of that sale* -- updating it later doesn't retroactively change past numbers.
    """

    __tablename__ = "item_cost_basis"

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    cost_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class MyListingSession(Base):
    """One specific listing (matched by ssi) posted under a registered vendor alias,
    tracked for its 24-hour (configurable) lifetime. Quantity decreases observed while it's
    still listed are confirmed sales; if it disappears before the window naturally expires,
    the remainder is also counted as sold (most likely a full sellout); if the window
    expires with the listing still up, any remainder is left uncounted (the stall closing is
    expected regardless of whether everything sold).
    """

    __tablename__ = "my_listing_sessions"
    __table_args__ = (
        UniqueConstraint("tracked_item_id", "ssi", name="uq_my_listing_session"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    ssi: Mapped[str] = mapped_column(String, nullable=False)
    seller_name: Mapped[str] = mapped_column(String, nullable=False)
    shop_name: Mapped[str | None] = mapped_column(String, nullable=True)
    map_name: Mapped[str | None] = mapped_column(String, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    initial_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    last_known_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    # 'active' | 'expired' | 'sold_out_early' | 'shop_removed'
    ended_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # null = normal outcome; 'shop_removed' = user marked as manually closed (not a sale)
    cost_per_unit: Mapped[float | None] = mapped_column(Float, nullable=True)
    # captured at window_start from ItemCostBasis -- nullable if no cost was set yet
    # Soft-delete: set when the user removes a bad entry from the My Sales page (e.g. a
    # listing they manually pulled rather than sold). The row and its MySaleEvent rows are
    # kept for audit purposes but excluded from the sales log/summary by default, and
    # db.repository.sync_my_listing_sessions permanently skips dismissed sessions so the
    # collector's next cycle does not resurrect them from the underlying observations.
    dismissed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class MySaleEvent(Base):
    """One confirmed sale chunk within a MyListingSession -- exists so 'when do my items
    sell more' can be computed from actual sale timestamps, not just session totals.
    """

    __tablename__ = "my_sale_events"
    __table_args__ = (
        UniqueConstraint("session_id", "occurred_at", name="uq_my_sale_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("my_listing_sessions.id"), nullable=False)
    tracked_item_id: Mapped[int] = mapped_column(ForeignKey("tracked_items.id"), nullable=False)
    map_name: Mapped[str | None] = mapped_column(String, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    quantity_sold: Mapped[int] = mapped_column(Integer, nullable=False)


class WatchRule(Base):
    """A price/supply watch rule, ported from D:\\Rag\\src's watches.json concept (e.g.
    "Elunium > 30000") -- deliberately independent of tracked_items, mirroring the
    original tool's flat rule-string shape rather than the item-registration catalog.

    state_active/last_price are persisted directly on the row (rather than reconstructed
    from NotificationEvent history) so the triggered/cleared/price_changed state machine in
    notifications/checker.py survives a collector restart without replaying old events.
    """

    __tablename__ = "watch_rules"
    __table_args__ = (
        UniqueConstraint("raw", name="uq_watch_rule_raw"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw: Mapped[str] = mapped_column(String, nullable=False)
    item_name: Mapped[str] = mapped_column(String, nullable=False)
    operator: Mapped[str] = mapped_column(String, nullable=False)  # '>' or '<'
    target_price: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    state_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Updated on every check regardless of whether the condition is met -- unlike
    # last_price (only set while the condition is active, for the notification state
    # machine), this is purely for display: "what's the market's cheapest price right now,
    # whether or not it has crossed the trigger threshold."
    last_checked_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class NotificationEvent(Base):
    """Persisted history of a fired watch-rule notification -- the original src/ tool was
    fire-and-forget (a text log only), this is the "results of the notification" record
    the dashboard surfaces.
    """

    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    watch_rule_id: Mapped[int] = mapped_column(ForeignKey("watch_rules.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # 'triggered'|'cleared'|'price_changed'
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    old_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class NotificationSettings(Base):
    """Single-row table (like SoldOutConfig) holding the global notification config,
    ported from D:\\Rag\\config.json -- editable live from the dashboard's Price Watcher
    settings section instead of requiring a restart.
    """

    __tablename__ = "notification_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    discord_token: Mapped[str | None] = mapped_column(String, nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String, nullable=True)
    user_mention: Mapped[str] = mapped_column(String, nullable=False, default="")
    # True = local sound beeps (winsound, no credentials needed); False = Discord.
    local_sound: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    variance_percent: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    min_items_below: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rule_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    store_type: Mapped[str] = mapped_column(String, nullable=False, default="BUY")
    server_type: Mapped[str] = mapped_column(String, nullable=False, default="FREYA")
    max_pages: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class MapAlias(Base):
    """Groups raw map_name values that are actually the same physical location under one
    canonical display name (e.g. abyss_03/abyss_04 -> "Abyss"). Raw observations are never
    rewritten -- this is a query-time lookup applied in the map analytics endpoints, so the
    underlying recorded map_name stays exactly as scraped.
    """

    __tablename__ = "map_aliases"
    __table_args__ = (
        UniqueConstraint("raw_map_name", name="uq_map_alias_raw"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    raw_map_name: Mapped[str] = mapped_column(String, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
