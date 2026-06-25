"""Nightly rollup job: aggregates listings_observations into hourly_stats,
daily_stats, and map_stats for a given date. Idempotent and rebuildable --
re-running for the same date recomputes those rows in place rather than
duplicating them. Raw observations remain the source of truth; these tables
exist purely so the dashboard doesn't have to scan raw data for every chart.
"""

import logging
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from db.models import DailyStat, HourlyStat, ListingObservation, MapStat  # noqa: E402
from db.session import get_session  # noqa: E402

logger = logging.getLogger(__name__)


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, datetime.min.time())
    return start, start + timedelta(days=1)


def _fetch_day_observations(session: Session, target_date: date) -> list[ListingObservation]:
    start, end = _day_bounds(target_date)
    stmt = select(ListingObservation).where(
        ListingObservation.observed_at >= start,
        ListingObservation.observed_at < end,
    )
    return list(session.scalars(stmt))


def compute_hourly_stats(session: Session, target_date: date) -> int:
    buckets: dict[tuple[int, int], list[ListingObservation]] = defaultdict(list)
    for obs in _fetch_day_observations(session, target_date):
        buckets[(obs.tracked_item_id, obs.observed_at.hour)].append(obs)

    date_str = target_date.isoformat()
    for (tracked_item_id, hour), obs_list in buckets.items():
        prices = [o.price for o in obs_list]
        existing = session.scalars(
            select(HourlyStat).where(
                HourlyStat.tracked_item_id == tracked_item_id,
                HourlyStat.date == date_str,
                HourlyStat.hour == hour,
            )
        ).first()
        row = existing or HourlyStat(tracked_item_id=tracked_item_id, date=date_str, hour=hour)
        row.avg_price = sum(prices) / len(prices)
        row.median_price = statistics.median(prices)
        row.min_price = min(prices)
        row.max_price = max(prices)
        row.total_quantity = sum(o.quantity for o in obs_list)
        row.listing_count = len(obs_list)
        if not existing:
            session.add(row)
            session.flush()  # makes this row visible to later existing-row lookups in this session
    return len(buckets)


def compute_daily_stats(session: Session, target_date: date) -> int:
    buckets: dict[int, list[ListingObservation]] = defaultdict(list)
    for obs in _fetch_day_observations(session, target_date):
        buckets[obs.tracked_item_id].append(obs)

    date_str = target_date.isoformat()
    weekday = target_date.weekday()  # 0 = Monday ... 6 = Sunday
    is_weekend = weekday >= 5
    for tracked_item_id, obs_list in buckets.items():
        prices = [o.price for o in obs_list]
        existing = session.scalars(
            select(DailyStat).where(
                DailyStat.tracked_item_id == tracked_item_id,
                DailyStat.date == date_str,
            )
        ).first()
        row = existing or DailyStat(tracked_item_id=tracked_item_id, date=date_str)
        row.weekday = weekday
        row.is_weekend = is_weekend
        row.avg_price = sum(prices) / len(prices)
        row.median_price = statistics.median(prices)
        row.min_price = min(prices)
        row.max_price = max(prices)
        row.total_quantity = sum(o.quantity for o in obs_list)
        row.listing_count = len(obs_list)
        if not existing:
            session.add(row)
            session.flush()
    return len(buckets)


def compute_map_stats(session: Session, target_date: date) -> int:
    buckets: dict[tuple[int, str], list[ListingObservation]] = defaultdict(list)
    for obs in _fetch_day_observations(session, target_date):
        if obs.map_name is None:
            continue
        buckets[(obs.tracked_item_id, obs.map_name)].append(obs)

    date_str = target_date.isoformat()
    for (tracked_item_id, map_name), obs_list in buckets.items():
        prices = [o.price for o in obs_list]
        existing = session.scalars(
            select(MapStat).where(
                MapStat.tracked_item_id == tracked_item_id,
                MapStat.map_name == map_name,
                MapStat.period_start == date_str,
                MapStat.period_end == date_str,
            )
        ).first()
        row = existing or MapStat(
            tracked_item_id=tracked_item_id,
            map_name=map_name,
            period_start=date_str,
            period_end=date_str,
        )
        row.avg_price = sum(prices) / len(prices)
        row.listing_count = len(obs_list)
        row.total_quantity = sum(o.quantity for o in obs_list)
        row.stddev_price = statistics.pstdev(prices) if len(prices) > 1 else 0.0
        if not existing:
            session.add(row)
            session.flush()
    return len(buckets)


def run_rollup_for_date(session: Session, target_date: date) -> dict:
    return {
        "hourly_rows": compute_hourly_stats(session, target_date),
        "daily_rows": compute_daily_stats(session, target_date),
        "map_rows": compute_map_stats(session, target_date),
    }


def distinct_observation_dates(session: Session) -> list[date]:
    stmt = select(ListingObservation.observed_at)
    return sorted({row.date() for row in session.scalars(stmt)})


def main(target_date: date | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    with get_session() as session:
        dates = [target_date] if target_date else distinct_observation_dates(session)
        if not dates:
            logger.info("No observations to roll up.")
            return
        for d in dates:
            stats = run_rollup_for_date(session, d)
            logger.info("%s: %s", d.isoformat(), stats)


if __name__ == "__main__":
    main()
