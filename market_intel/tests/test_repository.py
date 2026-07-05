from datetime import datetime, timedelta

from db.models import (
    ListingObservation,
    SaleEvent,
    ScrapeRun,
    SoldOutEvent,
)
from db.repository import (
    add_map_alias,
    add_tracked_item,
    delete_map_alias,
    delete_tracked_item,
    get_active_sold_out_counts,
    get_cached_shop_location,
    get_map_alias_lookup,
    get_sold_out_config,
    infer_and_persist_sales,
    infer_and_persist_sold_out,
    list_tracked_items,
    set_tracked_item_active,
    update_sold_out_config,
    upsert_shop_location,
)


def test_add_and_list_tracked_items(session):
    add_tracked_item(session, item_name="Elunium", server_name="FREYA", store_type="BUY")
    add_tracked_item(session, item_name="Oridecon", server_name="FREYA", store_type="BUY")
    session.commit()

    items = list_tracked_items(session)
    assert {i.item_name for i in items} == {"Elunium", "Oridecon"}


def test_list_tracked_items_active_only(session):
    item = add_tracked_item(session, item_name="Elunium")
    session.commit()
    set_tracked_item_active(session, item.id, False)
    session.commit()

    assert list_tracked_items(session, active_only=True) == []
    assert len(list_tracked_items(session)) == 1


def test_set_tracked_item_active_missing_raises(session):
    import pytest

    with pytest.raises(ValueError):
        set_tracked_item_active(session, 999, True)


def test_shop_location_cache_roundtrip(session):
    assert get_cached_shop_location(
        session, seller_name="Sicarius.", shop_name="-> ESTA AQUI <-", server_name="FREYA"
    ) is None

    upsert_shop_location(
        session,
        seller_name="Sicarius.",
        shop_name="-> ESTA AQUI <-",
        server_name="FREYA",
        map_id=None,
        map_name="prt_mk.gat",
        x_pos=163,
        y_pos=255,
    )
    session.commit()

    cached = get_cached_shop_location(
        session, seller_name="Sicarius.", shop_name="-> ESTA AQUI <-", server_name="FREYA"
    )
    assert cached is not None
    assert cached.map_name == "prt_mk.gat"
    assert (cached.x_pos, cached.y_pos) == (163, 255)


def test_shop_location_cache_upsert_overwrites(session):
    upsert_shop_location(
        session, seller_name="A", shop_name="B", server_name="FREYA",
        map_id=None, map_name="prt_mk.gat", x_pos=1, y_pos=1,
    )
    upsert_shop_location(
        session, seller_name="A", shop_name="B", server_name="FREYA",
        map_id=None, map_name="prt_in.gat", x_pos=2, y_pos=2,
    )
    session.commit()

    cached = get_cached_shop_location(session, seller_name="A", shop_name="B", server_name="FREYA")
    assert cached.map_name == "prt_in.gat"
    assert (cached.x_pos, cached.y_pos) == (2, 2)


def test_infer_and_persist_sales_writes_new_events(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=300,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 10, 0), price=100, quantity=250,
        ),
    ])
    session.commit()

    written = infer_and_persist_sales(session, item.id)
    session.commit()

    assert written == 1
    rows = session.query(SaleEvent).filter_by(tracked_item_id=item.id).all()
    assert len(rows) == 1
    assert rows[0].quantity_sold == 50
    assert rows[0].method == "decrease"


def test_infer_and_persist_sales_is_idempotent_across_repeated_calls(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=300,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 10, 0), price=100, quantity=250,
        ),
    ])
    session.commit()

    first_call = infer_and_persist_sales(session, item.id)
    session.commit()
    second_call = infer_and_persist_sales(session, item.id)  # same data, called again
    session.commit()

    assert first_call == 1
    assert second_call == 0  # already recorded -- not duplicated
    assert session.query(SaleEvent).filter_by(tracked_item_id=item.id).count() == 1


def test_get_sold_out_config_creates_defaults_on_first_call(session):
    config = get_sold_out_config(session)
    session.commit()
    assert config.threshold_ratio == 0.10
    assert config.quiet_hours_start == "00:00"
    assert config.quiet_hours_end == "06:00"


def test_update_sold_out_config_partial_update_and_clear(session):
    update_sold_out_config(session, threshold_ratio=0.25)
    session.commit()
    config = get_sold_out_config(session)
    assert config.threshold_ratio == 0.25
    assert config.quiet_hours_start == "00:00"  # untouched

    update_sold_out_config(session, clear_quiet_hours=True)
    session.commit()
    config = get_sold_out_config(session)
    assert config.quiet_hours_start is None
    assert config.quiet_hours_end is None


def test_infer_and_persist_sold_out_writes_and_is_idempotent(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=100,
            seller_name="Bob", shop_name="Bob's Shop", map_name="prt_mk.gat",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 10), price=100, quantity=5,
            seller_name="Bob", shop_name="Bob's Shop", map_name="prt_mk.gat",
        ),
    ])
    session.commit()

    first = infer_and_persist_sold_out(session, item.id)
    session.commit()
    second = infer_and_persist_sold_out(session, item.id)  # same data, called again
    session.commit()

    assert first == 1
    assert second == 0  # already recorded -- not duplicated
    rows = session.query(SoldOutEvent).filter_by(tracked_item_id=item.id).all()
    assert len(rows) == 1
    assert rows[0].baseline_quantity == 100
    assert rows[0].quantity_at_trigger == 5


def test_get_active_sold_out_counts_only_counts_still_listed_ssis(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 9, 10)
    t2 = datetime(2026, 1, 5, 9, 20)  # latest cycle -- only "B" appears here
    session.add_all([
        # ssi "A": triggers at t1, then disappears -- not present at the latest cycle (t2).
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t0, price=100, quantity=100, seller_name="Bob",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t1, price=100, quantity=5, seller_name="Bob",
        ),
        # ssi "B": triggers at t1 and is still present at the latest cycle (t2).
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=t0, price=100, quantity=100, seller_name="Carol",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=t1, price=100, quantity=5, seller_name="Carol",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=t2, price=100, quantity=5, seller_name="Carol",
        ),
    ])
    session.commit()

    infer_and_persist_sold_out(session, item.id)
    session.commit()

    counts = get_active_sold_out_counts(session)
    # Both "A" and "B" triggered, but only "B" is still listed at the latest (t2) cycle.
    assert counts == {item.id: 1}


def test_delete_tracked_item_cascades_sold_out_events(session):
    """Regression test: deleting an item must also remove its SoldOutEvent rows -- the
    real DB enforces the foreign key (PRAGMA foreign_keys=ON in db/session.py), so leaving
    orphaned rows behind would make deletion fail outright there, not just leave litter.
    """
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=100, seller_name="Bob",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 10), price=100, quantity=5, seller_name="Bob",
        ),
    ])
    session.commit()
    infer_and_persist_sold_out(session, item.id)
    session.commit()
    assert session.query(SoldOutEvent).filter_by(tracked_item_id=item.id).count() == 1

    delete_tracked_item(session, item.id)
    session.commit()

    assert session.query(SoldOutEvent).filter_by(tracked_item_id=item.id).count() == 0


def test_add_map_alias_upserts_on_readd(session):
    add_map_alias(session, raw_map_name="abyss_03", canonical_name="Abyss")
    session.commit()
    add_map_alias(session, raw_map_name="abyss_03", canonical_name="Renamed")
    session.commit()

    lookup = get_map_alias_lookup(session)
    assert lookup == {"abyss_03": "Renamed"}  # re-pointed, not duplicated


def test_get_map_alias_lookup_resolves_multiple_raw_names_to_one_canonical(session):
    add_map_alias(session, raw_map_name="abyss_03", canonical_name="Abyss")
    add_map_alias(session, raw_map_name="abyss_04", canonical_name="Abyss")
    session.commit()

    lookup = get_map_alias_lookup(session)
    assert lookup == {"abyss_03": "Abyss", "abyss_04": "Abyss"}


def test_delete_map_alias_missing_raises(session):
    import pytest

    with pytest.raises(ValueError):
        delete_map_alias(session, 999)
