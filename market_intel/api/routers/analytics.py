import statistics
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import (
    CurrentSnapshotOut,
    HourOfDayStatOut,
    ListingHistoryOut,
    MapStatOut,
    SaleEventOut,
    SaleMethodBreakdownOut,
    SalesByHourMapOut,
    SalesByHourOut,
    SellerStatOut,
    TrendOut,
    WeekdayStatOut,
    WeekendComparisonOut,
)
from db.models import DailyStat, HourlyStat, ListingObservation, MapStat, SaleEvent
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
        .where(ListingObservation.tracked_item_id == item_id)
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
    """Price-by-map comparison, aggregated across the date range."""
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

    sold_by_map: dict[str, int] = defaultdict(int)
    for event in db.scalars(_sale_events_query(item_id, start, end)):
        raw_name = event.map_name or "unknown"
        sold_by_map[alias_lookup.get(raw_name, raw_name)] += event.quantity_sold

    results = []
    for map_name, group in sorted(buckets.items(), key=lambda kv: -sum(r.listing_count for r in kv[1])):
        total_listings = sum(r.listing_count for r in group)
        weighted_avg = (
            sum(r.avg_price * r.listing_count for r in group) / total_listings
            if total_listings
            else 0.0
        )
        # Pooled variance across the per-day rows in this group: each day contributes its own
        # within-day variance plus the squared deviation of its mean from the combined mean,
        # weighted by listing_count -- correct for combining grouped stats without raw prices.
        if total_listings:
            pooled_variance = sum(
                r.listing_count * (r.stddev_price ** 2 + (r.avg_price - weighted_avg) ** 2)
                for r in group
            ) / total_listings
        else:
            pooled_variance = 0.0
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
    """Estimated units sold by hour-of-day. See MapStatOut.estimated_units_sold for the
    inference method and its caveat (minimum-bound estimate, see sales_inference.py).
    """
    buckets: dict[int, dict[str, int]] = defaultdict(lambda: {"sold": 0, "events": 0})
    for event in db.scalars(_sale_events_query(item_id, start, end)):
        bucket = buckets[event.sale_attributed_at.hour]
        bucket["sold"] += event.quantity_sold
        bucket["events"] += 1

    return [
        SalesByHourOut(hour=hour, estimated_units_sold=b["sold"], sale_events=b["events"])
        for hour, b in sorted(buckets.items())
    ]


@router.get("/{item_id}/sales-by-hour-map", response_model=list[SalesByHourMapOut])
def sales_by_hour_by_map(
    item_id: int,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Same estimated-units-sold inference as /sales-by-hour, broken down per map -- lets
    the user compare *when* an item sells fastest at each shop location, not just overall.
    """
    alias_lookup = get_map_alias_lookup(db)
    buckets: dict[tuple[str, int], int] = defaultdict(int)
    for event in db.scalars(_sale_events_query(item_id, start, end)):
        if not event.map_name:
            continue
        canonical_name = alias_lookup.get(event.map_name, event.map_name)
        buckets[(canonical_name, event.sale_attributed_at.hour)] += event.quantity_sold

    return [
        SalesByHourMapOut(map_name=map_name, hour=hour, estimated_units_sold=qty)
        for (map_name, hour), qty in sorted(buckets.items())
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
    obs_stmt = select(ListingObservation).where(ListingObservation.tracked_item_id == item_id)
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
