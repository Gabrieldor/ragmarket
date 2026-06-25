from datetime import date, datetime

from collector.rollup_jobs import compute_daily_stats, compute_hourly_stats, compute_map_stats
from db.models import DailyStat, HourlyStat, ListingObservation, MapStat, ScrapeRun
from db.repository import add_tracked_item


def _make_observation(session, run_id, item_id, observed_at, price, quantity, map_name=None):
    obs = ListingObservation(
        tracked_item_id=item_id,
        scrape_run_id=run_id,
        observed_at=observed_at,
        price=price,
        quantity=quantity,
        map_name=map_name,
    )
    session.add(obs)
    return obs


def test_compute_hourly_stats_aggregates_correctly(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    day = date(2026, 1, 5)
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 10, 0), price=100, quantity=5)
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 10, 30), price=200, quantity=10)
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 14, 0), price=300, quantity=1)
    session.commit()

    written = compute_hourly_stats(session, day)
    assert written == 2  # hour 10 and hour 14

    rows = {row.hour: row for row in session.query(HourlyStat)}
    assert rows[10].avg_price == 150
    assert rows[10].min_price == 100
    assert rows[10].max_price == 200
    assert rows[10].total_quantity == 15
    assert rows[10].listing_count == 2
    assert rows[14].avg_price == 300


def test_compute_hourly_stats_idempotent(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    day = date(2026, 1, 5)
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 10, 0), price=100, quantity=5)
    session.commit()

    first = compute_hourly_stats(session, day)
    second = compute_hourly_stats(session, day)
    session.commit()
    assert first == second == 1
    assert session.query(HourlyStat).count() == 1


def test_compute_daily_stats_weekday_and_weekend(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    # 2026-01-05 is a Monday (weekday=0), 2026-01-10 is a Saturday (weekday=5)
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 10, 0), price=100, quantity=1)
    _make_observation(session, run.id, item.id, datetime(2026, 1, 10, 10, 0), price=200, quantity=1)
    session.commit()

    compute_daily_stats(session, date(2026, 1, 5))
    compute_daily_stats(session, date(2026, 1, 10))
    session.commit()

    monday = session.query(DailyStat).filter_by(date="2026-01-05").one()
    saturday = session.query(DailyStat).filter_by(date="2026-01-10").one()
    assert monday.weekday == 0 and monday.is_weekend is False
    assert saturday.weekday == 5 and saturday.is_weekend is True


def test_compute_map_stats_groups_by_map(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    day = date(2026, 1, 5)
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 10, 0), price=100, quantity=10, map_name="prt_mk.gat")
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 11, 0), price=300, quantity=5, map_name="prt_mk.gat")
    _make_observation(session, run.id, item.id, datetime(2026, 1, 5, 12, 0), price=500, quantity=1, map_name="prt_in.gat")
    session.commit()

    written = compute_map_stats(session, day)
    session.commit()
    assert written == 2
    rows = {row.map_name: row for row in session.query(MapStat)}
    assert rows["prt_mk.gat"].avg_price == 200
    assert rows["prt_mk.gat"].listing_count == 2
    assert rows["prt_mk.gat"].total_quantity == 15
    assert rows["prt_in.gat"].avg_price == 500
    assert rows["prt_in.gat"].total_quantity == 1
