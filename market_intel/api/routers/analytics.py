import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import (
    CurrentSnapshotOut,
    HourOfDayStatOut,
    ListingHistoryOut,
    MapStatOut,
    OutlierObservationOut,
    SaleEventOut,
    SaleMethodBreakdownOut,
    SalesByHourMapOut,
    SalesByHourOut,
    SellerStatOut,
    TrendOut,
    WeekdayStatOut,
    WeekendComparisonOut,
)
from db.models import DailyStat, HourlyStat, ListingObservation, MapStat, SaleEvent, TrackedItem
from db.repository import get_map_alias_lookup
from db.session import get_db

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _date_filter(stmt, model, start: date | None, end: date | None):
    if start is not None:
        stmt = stmt.where(model.date >= start.isoformat())
    if end is not None:
        stmt = stmt.where(model.date <= end.isoformat())
    return stmt


def _sale_events_query(item_id: int, start: date | None, end: date | None):
    """Reads from the persisted SaleEvent table (written by the collector via
    db.repository.infer_and_persist_sales) rather than recomputing live -- see
    sales_inference.py for the detection method and SaleEvent for why this is persisted
    instead of ephemeral: it gives an audit trail to validate the method against real data.
    """
    stmt = select(SaleEvent).where(SaleEvent.tracked_item_id == item_id)
    if start is not None:
        stmt = stmt.where(SaleEvent.sale_attributed_at >= start.isoformat())
    if end is not None:
        stmt = stmt.where(SaleEvent.sale_attributed_at < (end + timedelta(days=1)).isoformat())
    return stmt


@router.get("/{item_id}/current", response_model=CurrentSnapshotOut)
def current_snapshot(item_id: int, db: Session = Depends(get_db)):
    """Stats from the most recent scrape only -- works immediately, even with just one
    cycle of data, unlike the hourly/weekday/map endpoints which depend on the nightly
    rollup job having already run at least once.
    """
    latest_observed_at = db.scalar(
        select(ListingObservation.observed_at)
        .where(ListingObservation.tracked_item_id == item_id, ListingObservation.is_outlier.is_(False))
        .order_by(ListingObservation.observed_at.desc())
        .limit(1)
    )
    if latest_observed_at is None:
        return CurrentSnapshotOut(
            observed_at=None, listing_count=0, total_quantity=0,
            avg_price=None, median_price=None, min_price=None, max_price=None,
        )

    rows = list(
        db.scalars(
            select(ListingObservation).where(
                ListingObservation.tracked_item_id == item_id,
                ListingObservation.observed_at == latest_observed_at,
                ListingObservation.is_outlier.is_(False),
            )
        )
    )
    prices = [r.price for r in rows]
    return CurrentSnapshotOut(
        observed_at=latest_observed_at,
        listing_count=len(rows),
        total_quantity=sum(r.quantity for r in rows),
        avg_price=sum(prices) / len(prices),
        median_price=statistics.median(prices),
        min_price=min(prices),
        max_price=max(prices),
    )


@router.get("/{item_id}/hourly", response_model=list[HourOfDayStatOut])
def hourly_pattern(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Average/median/min/max price by hour-of-day, aggregated across the date range."""
    stmt = select(HourlyStat).where(HourlyStat.tracked_item_id == item_id)
    stmt = _date_filter(stmt, HourlyStat, start, end)
    rows = list(db.scalars(stmt))

    buckets: dict[int, list[HourlyStat]] = defaultdict(list)
    for row in rows:
        buckets[row.hour].append(row)

    results = []
    for hour, group in sorted(buckets.items()):
        total_listings = sum(r.listing_count for r in group)
        weighted_avg = (
            sum(r.avg_price * r.listing_count for r in group) / total_listings
            if total_listings
            else 0.0
        )
        results.append(
            HourOfDayStatOut(
                hour=hour,
                avg_price=weighted_avg,
                median_price=statistics.median(r.median_price for r in group),
                min_price=min(r.min_price for r in group),
                max_price=max(r.max_price for r in group),
                total_quantity=sum(r.total_quantity for r in group),
                listing_count=total_listings,
                days_count=len(group),
            )
        )
    return results


@router.get("/{item_id}/weekday", response_model=list[WeekdayStatOut])
def weekday_pattern(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Average/median/min/max price by weekday, aggregated across the date range."""
    stmt = select(DailyStat).where(DailyStat.tracked_item_id == item_id)
    stmt = _date_filter(stmt, DailyStat, start, end)
    rows = list(db.scalars(stmt))

    buckets: dict[int, list[DailyStat]] = defaultdict(list)
    for row in rows:
        buckets[row.weekday].append(row)

    results = []
    for weekday, group in sorted(buckets.items()):
        total_listings = sum(r.listing_count for r in group)
        weighted_avg = (
            sum(r.avg_price * r.listing_count for r in group) / total_listings
            if total_listings
            else 0.0
        )
        results.append(
            WeekdayStatOut(
                weekday=weekday,
                is_weekend=weekday >= 5,
                avg_price=weighted_avg,
                median_price=statistics.median(r.median_price for r in group),
                min_price=min(r.min_price for r in group),
                max_price=max(r.max_price for r in group),
                total_quantity=sum(r.total_quantity for r in group),
                listing_count=total_listings,
                days_count=len(group),
            )
        )
    return results


@router.get("/{item_id}/weekend-vs-weekday", response_model=WeekendComparisonOut)
def weekend_vs_weekday(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    stmt = select(DailyStat).where(DailyStat.tracked_item_id == item_id)
    stmt = _date_filter(stmt, DailyStat, start, end)
    rows = list(db.scalars(stmt))

    weekday_rows = [r for r in rows if not r.is_weekend]
    weekend_rows = [r for r in rows if r.is_weekend]

    def _weighted_avg(group: list[DailyStat]) -> float | None:
        total = sum(r.listing_count for r in group)
        if not total:
            return None
        return sum(r.avg_price * r.listing_count for r in group) / total

    weekday_avg = _weighted_avg(weekday_rows)
    weekend_avg = _weighted_avg(weekend_rows)
    pct = None
    if weekday_avg and weekend_avg:
        pct = ((weekend_avg - weekday_avg) / weekday_avg) * 100

    return WeekendComparisonOut(
        weekday_avg_price=weekday_avg, weekend_avg_price=weekend_avg, percent_difference=pct
    )


@router.get("/{item_id}/map", response_model=list[MapStatOut])
def map_analysis(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Price-by-map comparison. Historical metrics (avg_price, stddev, est_units_sold)
    are aggregated across the date range; current_quantity and today_units_sold are always
    pinned to the present regardless of the date filter.
    """
    stmt = select(MapStat).where(MapStat.tracked_item_id == item_id)
    if start is not None:
        stmt = stmt.where(MapStat.period_start >= start.isoformat())
    if end is not None:
        stmt = stmt.where(MapStat.period_end <= end.isoformat())
    rows = list(db.scalars(stmt))
    alias_lookup = get_map_alias_lookup(db)

    buckets: dict[str, list[MapStat]] = defaultdict(list)
    for row in rows:
        raw_name = row.map_name or "unknown"
        buckets[alias_lookup.get(raw_name, raw_name)].append(row)

    # Historical: all-time sale events within the date filter
    sold_by_map: dict[str, int] = defaultdict(int)
    sale_price_num_by_map: dict[str, float] = defaultdict(float)
    sale_price_den_by_map: dict[str, int] = defaultdict(int)
    for event in db.scalars(_sale_events_query(item_id, start, end)):
        raw_name = event.map_name or "unknown"
        canonical = alias_lookup.get(raw_name, raw_name)
        sold_by_map[canonical] += event.quantity_sold
        if event.price is not None:
            sale_price_num_by_map[canonical] += event.price * event.quantity_sold
            sale_price_den_by_map[canonical] += event.quantity_sold

    # Current quantity + listing count: from the most recent scrape per map (ignores date filter)
    current_qty_by_map: dict[str, int] = defaultdict(int)
    current_listings_by_map: dict[str, int] = defaultdict(int)
    current_prices_by_map: dict[str, list[int]] = defaultdict(list)
    current_raw_names_by_canonical: dict[str, set[str]] = defaultdict(set)
    latest_at = db.scalar(
        select(ListingObservation.observed_at)
        .where(
            ListingObservation.tracked_item_id == item_id,
            ListingObservation.is_outlier.is_(False),
        )
        .order_by(ListingObservation.observed_at.desc())
        .limit(1)
    )
    if latest_at is not None:
        for obs in db.scalars(
            select(ListingObservation).where(
                ListingObservation.tracked_item_id == item_id,
                ListingObservation.observed_at == latest_at,
                ListingObservation.is_outlier.is_(False),
            )
        ):
            raw_name = obs.map_name or "unknown"
            canonical = alias_lookup.get(raw_name, raw_name)
            current_qty_by_map[canonical] += obs.quantity
            current_listings_by_map[canonical] += 1
            current_prices_by_map[canonical].append(obs.price)
            current_raw_names_by_canonical[canonical].add(raw_name)

    # Today's units sold: sale events since midnight Brazil time (UTC-3), ignores date filter
    _tz_brazil = timezone(timedelta(hours=-3))
    _today_brazil = datetime.now(_tz_brazil).date()
    today_start = datetime.combine(_today_brazil, datetime.min.time()) + timedelta(hours=3)
    today_sold_by_map: dict[str, int] = defaultdict(int)
    for event in db.scalars(
        select(SaleEvent).where(
            SaleEvent.tracked_item_id == item_id,
            SaleEvent.sale_attributed_at >= today_start,
        )
    ):
        raw_name = event.map_name or "unknown"
        today_sold_by_map[alias_lookup.get(raw_name, raw_name)] += event.quantity_sold

    results = []
    for map_name, group in sorted(buckets.items(), key=lambda kv: -sum(r.listing_count for r in kv[1])):
        total_listings = sum(r.listing_count for r in group)
        weighted_avg = (
            sum(r.avg_price * r.listing_count for r in group) / total_listings
            if total_listings
            else 0.0
        )
        if total_listings:
            pooled_variance = sum(
                r.listing_count * (r.stddev_price ** 2 + (r.avg_price - weighted_avg) ** 2)
                for r in group
            ) / total_listings
        else:
            pooled_variance = 0.0
        den = sale_price_den_by_map.get(map_name, 0)
        avg_sale_price = sale_price_num_by_map[map_name] / den if den else None
        results.append(
            MapStatOut(
                map_name=map_name,
                raw_map_names=sorted({r.map_name or "unknown" for r in group}),
                period_start=min(r.period_start for r in group),
                period_end=max(r.period_end for r in group),
                avg_price=weighted_avg,
                listing_count=total_listings,
                total_quantity=sum(r.total_quantity for r in group),
                stddev_price=pooled_variance ** 0.5,
                estimated_units_sold=sold_by_map.get(map_name, 0),
                avg_sale_price=avg_sale_price,
                current_quantity=current_qty_by_map.get(map_name, 0),
                current_listing_count=current_listings_by_map.get(map_name, 0),
                today_units_sold=today_sold_by_map.get(map_name, 0),
            )
        )

    # Fallback: maps visible in the current scrape or today's sales but with no MapStat
    # rows yet (rollup hasn't run since the item was added, or all observations had NULL
    # map_name until recently). Show current data so the table is never empty while live.
    today_iso = _today_brazil.isoformat()
    for map_name in sorted(set(current_qty_by_map) | set(today_sold_by_map)):
        if map_name in buckets:
            continue
        prices = current_prices_by_map.get(map_name, [])
        den = sale_price_den_by_map.get(map_name, 0)
        results.append(
            MapStatOut(
                map_name=map_name,
                raw_map_names=sorted(current_raw_names_by_canonical.get(map_name, {map_name})),
                period_start=today_iso,
                period_end=today_iso,
                avg_price=sum(prices) / len(prices) if prices else 0.0,
                listing_count=0,
                total_quantity=0,
                stddev_price=statistics.pstdev(prices) if len(prices) > 1 else 0.0,
                estimated_units_sold=sold_by_map.get(map_name, 0),
                avg_sale_price=sale_price_num_by_map[map_name] / den if den else None,
                current_quantity=current_qty_by_map.get(map_name, 0),
                current_listing_count=current_listings_by_map.get(map_name, 0),
                today_units_sold=today_sold_by_map.get(map_name, 0),
            )
        )

    return results


@router.get("/{item_id}/sale-events", response_model=list[SaleEventOut])
def sale_events_drilldown(
    item_id: int,
    method: str | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
):
    """Raw persisted SaleEvent rows for the sold-out audit view -- lets the user drill down
    from a method's aggregate count/quantity to the individual listings behind it.
    """
    stmt = _sale_events_query(item_id, start, end)
    if method is not None:
        stmt = stmt.where(SaleEvent.method == method)
    stmt = stmt.order_by(SaleEvent.sale_attributed_at.desc()).limit(limit)
    return list(db.scalars(stmt))


@router.get("/{item_id}/sale-method-breakdown", response_model=list[SaleMethodBreakdownOut])
def sale_method_breakdown(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Counts/quantities of inferred sale events grouped by detection method -- audits how
    much of estimated_units_sold rests on the sellout-grace-window inference (riskier) vs.
    the direct quantity-decrease signal (more reliable). See SaleEvent.method.
    """
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "qty": 0})
    for event in db.scalars(_sale_events_query(item_id, start, end)):
        bucket = buckets[event.method]
        bucket["count"] += 1
        bucket["qty"] += event.quantity_sold
    return [
        SaleMethodBreakdownOut(method=method, event_count=b["count"], total_quantity_sold=b["qty"])
        for method, b in sorted(buckets.items())
    ]


@router.get("/{item_id}/sales-by-hour", response_model=list[SalesByHourOut])
def sales_by_hour(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Average estimated units sold per hour-of-day across all days in the range.

    Groups sale events by (date, hour) first to get per-day totals, then averages
    those daily totals per hour -- so '1 AM' shows the mean of each day's 1 AM
    sales rather than an ever-growing cumulative sum.
    """
    # Per-day totals: (date, hour) → {sold, price_num, price_den}
    # Use Brazil local time so the chart shows hours meaningful to the user.
    daily: dict[tuple, dict] = defaultdict(lambda: {"sold": 0, "revenue": 0.0, "price_num": 0.0, "price_den": 0})
    for event in db.scalars(_sale_events_query(item_id, start, end)):
        brt = event.sale_attributed_at - timedelta(hours=3)
        key = (brt.date(), brt.hour)
        daily[key]["sold"] += event.quantity_sold
        if event.price is not None:
            daily[key]["revenue"] += event.price * event.quantity_sold
            daily[key]["price_num"] += event.price * event.quantity_sold
            daily[key]["price_den"] += event.quantity_sold

    # Average across days per hour
    hourly: dict[int, dict] = defaultdict(
        lambda: {"sold_values": [], "revenue_values": [], "price_num": 0.0, "price_den": 0}
    )
    for (_, hour), vals in daily.items():
        hourly[hour]["sold_values"].append(vals["sold"])
        hourly[hour]["revenue_values"].append(vals["revenue"])
        hourly[hour]["price_num"] += vals["price_num"]
        hourly[hour]["price_den"] += vals["price_den"]

    return [
        SalesByHourOut(
            hour=hour,
            estimated_units_sold=statistics.mean(b["sold_values"]),
            estimated_revenue=statistics.mean(b["revenue_values"]),
            sale_events=len(b["sold_values"]),
            avg_sale_price=b["price_num"] / b["price_den"] if b["price_den"] else None,
        )
        for hour, b in sorted(hourly.items())
    ]


@router.get("/{item_id}/sales-by-hour-map", response_model=list[SalesByHourMapOut])
def sales_by_hour_by_map(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Average estimated units sold per (map, hour-of-day) across all days in the range.

    Same averaging approach as /sales-by-hour: groups by (map, hour, date) first to get
    daily totals, then averages those per (map, hour).
    """
    alias_lookup = get_map_alias_lookup(db)

    # Per-day totals: (map, hour, date) → qty  — Brazil local time for the hour bucket
    daily: dict[tuple, int] = defaultdict(int)
    for event in db.scalars(_sale_events_query(item_id, start, end)):
        if not event.map_name:
            continue
        canonical = alias_lookup.get(event.map_name, event.map_name)
        brt = event.sale_attributed_at - timedelta(hours=3)
        key = (canonical, brt.hour, brt.date())
        daily[key] += event.quantity_sold

    # Average across days per (map, hour)
    map_hour: dict[tuple[str, int], list[int]] = defaultdict(list)
    for (map_name, hour, _), qty in daily.items():
        map_hour[(map_name, hour)].append(qty)

    return [
        SalesByHourMapOut(map_name=name, hour=hour, estimated_units_sold=statistics.mean(vals))
        for (name, hour), vals in sorted(map_hour.items())
    ]


@router.get("/{item_id}/sellers", response_model=list[SellerStatOut])
def seller_analysis(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Per-seller average price and deviation from that day's market average.

    A consistently negative deviation means the seller tends to undercut the
    market; positive means they tend to price above it.
    """
    obs_stmt = select(ListingObservation).where(
        ListingObservation.tracked_item_id == item_id,
        ListingObservation.is_outlier.is_(False),
    )
    if start is not None:
        obs_stmt = obs_stmt.where(ListingObservation.observed_at >= start.isoformat())
    if end is not None:
        obs_stmt = obs_stmt.where(ListingObservation.observed_at < (end + timedelta(days=1)).isoformat())
    observations = list(db.scalars(obs_stmt))
    if not observations:
        return []

    daily_stmt = select(DailyStat).where(DailyStat.tracked_item_id == item_id)
    daily_stmt = _date_filter(daily_stmt, DailyStat, start, end)
    daily_avg_by_date = {row.date: row.avg_price for row in db.scalars(daily_stmt)}

    # "Current stock" must match what searching the market right now would show -- only the
    # most recent observation cycle within the requested range, not every distinct listing
    # this seller has ever posted historically (which would overcount a seller who
    # repeatedly sells out and relists over weeks).
    latest_observed_at = max(o.observed_at for o in observations)

    by_seller: dict[str, list[ListingObservation]] = defaultdict(list)
    for obs in observations:
        if not obs.seller_name:
            continue
        by_seller[obs.seller_name].append(obs)

    results = []
    for seller_name, obs_list in by_seller.items():
        prices = [o.price for o in obs_list]
        deviations = [
            o.price - day_avg
            for o in obs_list
            if (day_avg := daily_avg_by_date.get(o.observed_at.date().isoformat())) is not None
        ]
        current_quantity = sum(o.quantity for o in obs_list if o.observed_at == latest_observed_at)
        if current_quantity == 0:
            # Not actually listed right now (sold out, or pushed off the scraper's
            # max_pages=1 view by other listings) -- this table is for "who's undercutting
            # the market right now", not a historical roster. See /listing-history for the
            # full lifecycle/quantity-sold record of every listing this item has ever had.
            continue

        results.append(
            SellerStatOut(
                seller_name=seller_name,
                listing_count=len(obs_list),
                total_quantity=current_quantity,
                avg_price=sum(prices) / len(prices),
                avg_deviation_from_daily_avg=(
                    sum(deviations) / len(deviations) if deviations else 0.0
                ),
            )
        )

    results.sort(key=lambda r: r.avg_deviation_from_daily_avg)
    return results


@router.get("/{item_id}/listing-history", response_model=list[ListingHistoryOut])
def listing_history(item_id: int, db: Session = Depends(get_db)):
    """Full lifecycle of every distinct listing (ssi) this item has ever had: when it
    appeared, when it was last seen, whether it's still up, and how much it has sold
    (reusing the already-persisted SaleEvent rows by ssi -- see sales_inference.py).
    """
    observations = list(
        db.scalars(
            select(ListingObservation)
            .where(ListingObservation.tracked_item_id == item_id, ListingObservation.ssi.is_not(None))
            .order_by(ListingObservation.observed_at)
        )
    )
    if not observations:
        return []

    latest_observed_at = max(o.observed_at for o in observations)

    by_ssi: dict[str, list[ListingObservation]] = defaultdict(list)
    for obs in observations:
        by_ssi[obs.ssi].append(obs)

    sold_by_ssi: dict[str, int] = defaultdict(int)
    for event in db.scalars(select(SaleEvent).where(SaleEvent.tracked_item_id == item_id)):
        sold_by_ssi[event.ssi] += event.quantity_sold

    results = []
    for ssi, obs_list in by_ssi.items():
        first, last = obs_list[0], obs_list[-1]  # obs_list is already in observed_at order
        results.append(
            ListingHistoryOut(
                ssi=ssi,
                seller_name=last.seller_name,
                shop_name=last.shop_name,
                map_name=last.map_name,
                first_observed_at=first.observed_at,
                last_observed_at=last.observed_at,
                is_active=last.observed_at == latest_observed_at,
                initial_quantity=first.quantity,
                last_known_quantity=last.quantity,
                quantity_sold=sold_by_ssi.get(ssi, 0),
            )
        )

    # Active listings first, then most-recently-first-seen first within each group.
    results.sort(key=lambda r: (not r.is_active, -r.first_observed_at.timestamp()))
    return results


@router.get("/{item_id}/trend", response_model=TrendOut)
def trend_analysis(
    item_id: int,
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Compare the average price over the most recent N days vs. the N days before that."""
    today = date.today()
    recent_start = today - timedelta(days=days)
    prior_start = recent_start - timedelta(days=days)

    stmt = select(DailyStat).where(
        DailyStat.tracked_item_id == item_id,
        DailyStat.date >= prior_start.isoformat(),
        DailyStat.date <= today.isoformat(),
    )
    rows = list(db.scalars(stmt))

    recent_rows = [r for r in rows if r.date >= recent_start.isoformat()]
    prior_rows = [r for r in rows if r.date < recent_start.isoformat()]

    def _weighted_avg(group: list[DailyStat]) -> float | None:
        total = sum(r.listing_count for r in group)
        if not total:
            return None
        return sum(r.avg_price * r.listing_count for r in group) / total

    recent_avg = _weighted_avg(recent_rows)
    prior_avg = _weighted_avg(prior_rows)
    pct = None
    if recent_avg is not None and prior_avg:
        pct = ((recent_avg - prior_avg) / prior_avg) * 100

    return TrendOut(
        tracked_item_id=item_id,
        recent_period_days=days,
        recent_avg_price=recent_avg,
        prior_avg_price=prior_avg,
        percent_change=pct,
    )


@router.get("/outliers", response_model=list[OutlierObservationOut])
def list_outliers(
    item_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    limit: int = Query(default=200, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """All observations flagged as outliers (price >5x the cycle's median), with the
    cycle's clean median and the price multiplier included for context.
    """
    stmt = select(ListingObservation).where(ListingObservation.is_outlier.is_(True))
    if item_id is not None:
        stmt = stmt.where(ListingObservation.tracked_item_id == item_id)
    if start is not None:
        stmt = stmt.where(ListingObservation.observed_at >= start.isoformat())
    if end is not None:
        stmt = stmt.where(ListingObservation.observed_at < (end + timedelta(days=1)).isoformat())
    stmt = stmt.order_by(ListingObservation.observed_at.desc()).offset(offset).limit(limit)
    outliers = list(db.scalars(stmt))

    if not outliers:
        return []

    # Build a name lookup for tracked items.
    item_ids = {o.tracked_item_id for o in outliers}
    items = {
        row.id: (row.display_name or row.item_name)
        for row in db.scalars(select(TrackedItem).where(TrackedItem.id.in_(item_ids)))
    }

    # For each unique (tracked_item_id, observed_at) cycle that has outliers, compute the
    # clean median from the non-outlier rows in that same cycle.
    cycle_keys = {(o.tracked_item_id, o.observed_at) for o in outliers}
    cycle_medians: dict[tuple, int] = {}
    for (tid, ts) in cycle_keys:
        clean_prices = list(db.scalars(
            select(ListingObservation.price).where(
                ListingObservation.tracked_item_id == tid,
                ListingObservation.observed_at == ts,
                ListingObservation.is_outlier.is_(False),
            )
        ))
        if clean_prices:
            cycle_medians[(tid, ts)] = int(statistics.median(clean_prices))
        else:
            # Edge case: entire cycle is outliers — use their own median as reference.
            all_prices = list(db.scalars(
                select(ListingObservation.price).where(
                    ListingObservation.tracked_item_id == tid,
                    ListingObservation.observed_at == ts,
                )
            ))
            cycle_medians[(tid, ts)] = int(statistics.median(all_prices)) if all_prices else 0

    results = []
    for obs in outliers:
        median = cycle_medians.get((obs.tracked_item_id, obs.observed_at), 0)
        results.append(OutlierObservationOut(
            id=obs.id,
            tracked_item_id=obs.tracked_item_id,
            item_name=items.get(obs.tracked_item_id, "Unknown"),
            observed_at=obs.observed_at,
            price=obs.price,
            quantity=obs.quantity,
            seller_name=obs.seller_name,
            shop_name=obs.shop_name,
            map_name=obs.map_name,
            cycle_median_price=median,
            price_multiple=round(obs.price / median, 1) if median else 0.0,
        ))
    return results
