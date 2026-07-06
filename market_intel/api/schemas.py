from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TrackedItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_name: str
    display_name: str | None
    site_item_id: int | None
    server_name: str
    store_type: str
    is_active: bool
    poll_interval_override: int | None
    sold_out_enabled: bool
    created_at: datetime
    updated_at: datetime


class TrackedItemCreate(BaseModel):
    item_name: str
    display_name: str | None = None
    server_name: str = "FREYA"
    store_type: str = "BUY"
    poll_interval_override: int | None = None


class TrackedItemUpdate(BaseModel):
    is_active: bool | None = None
    poll_interval_override: int | None = None
    sold_out_enabled: bool | None = None


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tracked_item_id: int
    observed_at: datetime
    ssi: str | None
    item_id: int | None
    price: int
    quantity: int
    seller_name: str | None
    shop_name: str | None
    server_name: str | None
    store_type: str | None
    map_name: str | None
    x_pos: int | None
    y_pos: int | None
    location_source: str | None
    page_num: int | None
    rank_on_page: int | None


class HourlyStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: str
    hour: int
    avg_price: float
    median_price: float
    min_price: int
    max_price: int
    total_quantity: int
    listing_count: int


class DailyStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    date: str
    weekday: int
    is_weekend: bool
    avg_price: float
    median_price: float
    min_price: int
    max_price: int
    total_quantity: int
    listing_count: int


class MapStatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    map_name: str | None
    # The raw map_name values (pre-alias-resolution) aggregated into this row -- more than
    # one when a MapAlias group merges several raw names under one canonical display name.
    # Needed so the dashboard can query raw observations/listings for this row (they're
    # stored under the raw names, never the canonical one) -- see api/routers/observations.py.
    raw_map_names: list[str]
    period_start: str
    period_end: str
    median_price: float
    listing_count: int
    total_quantity: int
    # True population stddev of raw per-listing prices across the range for this map (see
    # api/routers/analytics.py:map_analysis) -- computed directly from the raw observations,
    # not derived from per-day rollup stddevs.
    stddev_price: float
    # Inferred from (1) quantity decreases on the same listing (matched by ssi) across
    # consecutive scrapes, and (2) listings that disappear entirely, confirmed as sold out
    # only after a grace window passes with no matching relist (same seller) -- if a relist
    # appears, only the shortfall counts, not the full original quantity. Still a
    # minimum-bound estimate: very recent disappearances within the grace window are left
    # out (pending) rather than guessed at. See analytics.py:_compute_sold_deltas.
    estimated_units_sold: int
    median_sale_price: float | None  # quantity-weighted median price across inferred sale events; null if no sales
    current_quantity: int         # sum of qty in the most recent scrape for this map (current stock)
    current_listing_count: int    # number of listings in the most recent scrape for this map
    today_units_sold: int         # units sold today (since midnight local time)


class HourOfDayStatOut(BaseModel):
    """Aggregated across all days in range -- e.g. 'usually cheapest 02:00-05:00'."""

    hour: int
    avg_price: float
    median_price: float
    min_price: int
    max_price: int
    total_quantity: int
    listing_count: int
    days_count: int


class SalesByHourOut(BaseModel):
    """See MapStatOut.estimated_units_sold -- same inference method and same caveat."""

    hour: int
    estimated_units_sold: float  # average daily units sold at this hour (not cumulative)
    sale_events: int             # number of days that had sales at this hour
    median_sale_price: float | None  # quantity-weighted median price; null if no priced sale events


class SalesByHourMapOut(BaseModel):
    """Same inference method as SalesByHourOut, broken down by map -- lets the user see
    not just *when* an item tends to sell, but *where* it sells fastest at each hour.
    """

    map_name: str
    hour: int
    estimated_units_sold: float  # average daily units sold at this (map, hour)


class MapAliasOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_map_name: str
    canonical_name: str
    created_at: datetime


class MapAliasCreate(BaseModel):
    """Groups one or more raw map_name values under one canonical display name, e.g.
    canonical_name="Abyss", raw_map_names=["abyss_03", "abyss_04"].
    """

    canonical_name: str
    raw_map_names: list[str]


class WeekdayStatOut(BaseModel):
    weekday: int
    is_weekend: bool
    avg_price: float
    median_price: float
    min_price: int
    max_price: int
    total_quantity: int
    listing_count: int
    days_count: int


class WeekendComparisonOut(BaseModel):
    weekday_median_price: float | None
    weekend_median_price: float | None
    percent_difference: float | None  # positive => weekend more expensive


class SellerStatOut(BaseModel):
    seller_name: str
    listing_count: int  # number of observation rows (listings seen across polls), not stock
    total_quantity: int  # sum of item quantity (stock) across all this seller's listings
    median_price: float
    median_deviation_from_daily_median: float  # negative = consistently undercutting the market


class ListingHistoryOut(BaseModel):
    """One distinct listing's (ssi) full lifecycle for a tracked item -- when it appeared,
    when it was last seen, whether it's still up, and how much it has sold (reusing the
    already-persisted SaleEvent rows by ssi, see sales_inference.py). This is the
    historical record the Sellers table (now current-stock-only) no longer shows.
    """

    ssi: str
    seller_name: str | None
    shop_name: str | None
    map_name: str | None
    first_observed_at: datetime
    last_observed_at: datetime
    is_active: bool
    initial_quantity: int
    last_known_quantity: int
    quantity_sold: int


class TrendOut(BaseModel):
    tracked_item_id: int
    recent_period_days: int
    recent_median_price: float | None
    prior_median_price: float | None
    percent_change: float | None


class CollectorStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    state: str  # 'starting' | 'scraping' | 'sleeping' | 'rate_limited' | 'offline' | 'paused'
    current_item_name: str | None
    next_cycle_at: datetime | None
    next_item_at: datetime | None
    consecutive_rate_limits: int
    paused: bool
    updated_at: datetime | None


class CurrentSnapshotOut(BaseModel):
    """Computed directly from the most recent scrape's raw observations -- unlike the
    hourly/weekday/map endpoints, this works immediately with as little as one cycle of
    data, since it doesn't depend on the nightly rollup job having run yet.
    """

    observed_at: datetime | None
    listing_count: int
    total_quantity: int
    avg_price: float | None
    median_price: float | None
    min_price: int | None
    max_price: int | None


class SaleEventOut(BaseModel):
    """Raw drill-down row for the sold-out audit view -- one persisted SaleEvent."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    tracked_item_id: int
    ssi: str
    seller_name: str | None
    map_name: str | None
    quantity_sold: int
    price: int | None
    sale_attributed_at: datetime
    method: str  # 'decrease' | 'sellout_no_relist' | 'sellout_partial_relist'
    relisted_ssi: str | None
    relisted_quantity: int | None


class SaleMethodBreakdownOut(BaseModel):
    """Counts/quantities of inferred global-market sale events, grouped by detection
    method -- lets the user judge how much of estimated_units_sold rests on the
    riskier sellout-grace-window inference vs. the more direct quantity-decrease signal.
    """

    method: str
    event_count: int
    total_quantity_sold: int


class SoldOutConfigOut(BaseModel):
    """The global low-stock detection config -- editable live from the Settings page."""

    model_config = ConfigDict(from_attributes=True)

    threshold_ratio: float
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    updated_at: datetime


class SoldOutConfigUpdate(BaseModel):
    threshold_ratio: float | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    clear_quiet_hours: bool = False


class SoldOutEventOut(BaseModel):
    """One persisted low-stock trigger -- see sold_out_inference.py for the detection
    method and its quiet-hours caveat.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tracked_item_id: int
    ssi: str
    seller_name: str | None
    shop_name: str | None
    map_name: str | None
    baseline_quantity: int
    quantity_at_trigger: int
    threshold_ratio: float
    triggered_at: datetime
    recorded_at: datetime


class SoldOutSummaryOut(BaseModel):
    """One entry per tracked item with at least one currently-active low-stock listing --
    drives the Overview page's badge.
    """

    tracked_item_id: int
    active_count: int


class ScraperConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    outlier_factor: float
    updated_at: datetime


class ScraperConfigUpdate(BaseModel):
    outlier_factor: float


class CollectorConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    poll_interval_seconds: int
    item_delay_seconds: float
    location_click_delay_seconds: float
    updated_at: datetime


class CollectorConfigUpdate(BaseModel):
    poll_interval_seconds: int | None = None
    item_delay_seconds: float | None = None
    location_click_delay_seconds: float | None = None


class OutlierObservationOut(BaseModel):
    id: int
    tracked_item_id: int
    item_name: str
    observed_at: datetime
    price: int
    quantity: int
    seller_name: str | None
    shop_name: str | None
    map_name: str | None
    cycle_median_price: int
    price_multiple: float


class WatchRuleOut(BaseModel):
    """A price/supply watch rule -- ported from D:\\Rag\\src's watches.json concept, see
    notifications/checker.py for the detection logic.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    raw: str
    item_name: str
    operator: str
    target_price: int
    required_refine: int | None
    required_slot: int | None
    required_map: str | None
    excluded_maps: str | None
    required_min_qty: int | None
    is_active: bool
    state_active: bool
    last_price: int | None
    last_checked_price: int | None
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WatchRuleCreate(BaseModel):
    raw: str  # e.g. "Elunium > 30000" -- parsed server-side via notifications.rule_parser


class WatchRuleUpdate(BaseModel):
    is_active: bool | None = None


class NotificationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    watch_rule_id: int
    event_type: str  # 'triggered' | 'cleared' | 'price_changed'
    price: int | None
    old_price: int | None
    created_at: datetime


class NotificationSettingsOut(BaseModel):
    """The global price-watcher config -- editable live from the Price Watcher page.
    discord_token is masked (only the last 4 characters are returned) since it's a
    credential -- never echoed back to the browser unmasked.
    """

    discord_token_masked: str | None
    channel_id: str | None
    user_mention: str
    local_sound: bool
    variance_percent: float
    min_items_below: int
    rule_delay_seconds: float
    store_type: str
    server_type: str
    max_pages: int
    global_excluded_maps: str | None
    updated_at: datetime


class NotificationSettingsUpdate(BaseModel):
    discord_token: str | None = None
    channel_id: str | None = None
    user_mention: str | None = None
    local_sound: bool | None = None
    variance_percent: float | None = None
    min_items_below: int | None = None
    rule_delay_seconds: float | None = None
    store_type: str | None = None
    server_type: str | None = None
    max_pages: int | None = None
    global_excluded_maps: str | None = None


class MapCountOut(BaseModel):
    map_name: str
    quantity: int


class ThresholdSideOut(BaseModel):
    total: int
    by_map: list[MapCountOut]


class ThresholdBreakdownOut(BaseModel):
    available: ThresholdSideOut | None
    sold: ThresholdSideOut | None
