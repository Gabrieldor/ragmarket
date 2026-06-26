from datetime import datetime, timedelta

from db.models import (
    ItemCostBasis,
    ListingObservation,
    MyListingSession,
    MySaleEvent,
    SaleEvent,
    ScrapeRun,
    SoldOutEvent,
)
from db.repository import (
    add_map_alias,
    add_tracked_item,
    add_vendor_alias,
    delete_map_alias,
    delete_tracked_item,
    get_active_sold_out_counts,
    get_cached_shop_location,
    get_current_cost_basis,
    get_map_alias_lookup,
    get_sold_out_config,
    infer_and_persist_sales,
    infer_and_persist_sold_out,
    list_tracked_items,
    mark_shop_removed,
    set_item_cost_basis,
    set_tracked_item_active,
    sync_my_listing_sessions,
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


def test_cost_basis_versioning_does_not_overwrite_history(session):
    item = add_tracked_item(session, item_name="Elunium")
    set_item_cost_basis(session, item.id, 1000)
    session.commit()
    set_item_cost_basis(session, item.id, 1500)
    session.commit()

    assert get_current_cost_basis(session, item.id).cost_per_unit == 1500
    history = session.query(ItemCostBasis).all()
    assert len(history) == 2  # both versions kept, not overwritten


def test_sync_my_listing_sessions_creates_session_and_chunk(session):
    item = add_tracked_item(session, item_name="Elunium")
    add_vendor_alias(session, "MyAlt")
    t0 = datetime(2026, 1, 5, 9, 0)
    set_item_cost_basis(session, item.id, 1000, effective_from=t0 - timedelta(days=1))
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    t1 = t0 + timedelta(hours=2)
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t0, price=20000, quantity=100, seller_name="MyAlt", shop_name="Shop",
            map_name="prt_mk.gat",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t1, price=20000, quantity=60, seller_name="MyAlt", shop_name="Shop",
            map_name="prt_mk.gat",
        ),
    ])
    session.commit()

    written = sync_my_listing_sessions(session, item.id)
    session.commit()

    assert written == 1
    sessions = session.query(MyListingSession).filter_by(tracked_item_id=item.id).all()
    assert len(sessions) == 1
    assert sessions[0].total_quantity_sold == 40
    assert sessions[0].cost_per_unit == 1000
    assert sessions[0].status == "active"

    chunks = session.query(MySaleEvent).filter_by(session_id=sessions[0].id).all()
    assert len(chunks) == 1
    assert chunks[0].quantity_sold == 40


def test_sync_my_listing_sessions_is_idempotent(session):
    item = add_tracked_item(session, item_name="Elunium")
    add_vendor_alias(session, "MyAlt")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = t0 + timedelta(hours=2)
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t0, price=20000, quantity=100, seller_name="MyAlt",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t1, price=20000, quantity=60, seller_name="MyAlt",
        ),
    ])
    session.commit()

    first = sync_my_listing_sessions(session, item.id)
    session.commit()
    second = sync_my_listing_sessions(session, item.id)
    session.commit()

    assert first == 1
    assert second == 0
    assert session.query(MyListingSession).filter_by(tracked_item_id=item.id).count() == 1
    assert session.query(MySaleEvent).count() == 1


def test_sync_my_listing_sessions_noop_without_registered_aliases(session):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    session.add(
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=20000, quantity=100,
            seller_name="SomeRandomSeller",
        )
    )
    session.commit()

    written = sync_my_listing_sessions(session, item.id)
    assert written == 0
    assert session.query(MyListingSession).count() == 0


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


# ── Regression tests: shop_removed continuation bug ────────────────────────────

def _obs(item_id, run_id, ssi, observed_at, qty, seller="MyAlt", price=20000):
    return ListingObservation(
        tracked_item_id=item_id, scrape_run_id=run_id, ssi=ssi,
        observed_at=observed_at, price=price, quantity=qty,
        seller_name=seller, shop_name="MyShop", map_name="prt_mk.gat",
    )


def test_continuation_does_not_double_count_old_ssi_on_second_sync(session):
    """Regression: after mark_shop_removed + new relist, a subsequent sync_my_listing_sessions
    call used to re-match the old SSI's compute result as ANOTHER continuation, adding the
    full expired qty to the new order's total as if it sold.

    The bug required two sync cycles:
      Cycle 1: only A observed → A=sold_out_early(100). User marks shop_removed.
      Cycle 2: B appears for first time → continuation absorbs B into A's session.
               Session now has SSI=B, ended_reason=None (bug fix), total=0.
      Cycle 3 (BUG cycle): without the fix, existing_sessions={B(ended_reason=shop_removed)};
               A's raw compute result (still sold_out_early=100) finds the session as a
               continuation → total += 100 → B shows 100 as sold.
    """
    item = add_tracked_item(session, item_name="Elunium")
    add_vendor_alias(session, "MyAlt")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    t0 = datetime(2026, 6, 1, 10, 0)
    t1 = t0 + timedelta(hours=1)   # next scrape: A is gone → sold_out_early
    t2 = t1 + timedelta(hours=1)   # B still there

    # CYCLE 1: only A is observed.
    session.add(_obs(item.id, run.id, "A", t0, qty=100))
    session.commit()

    # Simulate that we scraped at t1 and A was gone (no A observation at t1).
    # Add a non-alias observation at t1 so the cycle clock advances past t0.
    run2 = ScrapeRun(status="success")
    session.add(run2)
    session.flush()
    session.add(_obs(item.id, run2.id, "SENTINEL", t1, qty=50, seller="OtherSeller"))
    session.commit()

    sync_my_listing_sessions(session, item.id)
    session.commit()

    a_session = session.query(MyListingSession).filter_by(tracked_item_id=item.id, ssi="A").first()
    assert a_session is not None
    assert a_session.status == "sold_out_early"
    assert a_session.total_quantity_sold == 100

    # User marks A as shop_removed (they pulled the shop; nothing actually sold).
    mark_shop_removed(session, a_session.id)
    session.commit()
    assert a_session.total_quantity_sold == 0
    assert a_session.status == "shop_removed"

    # CYCLE 2: B appears for the first time. Continuation absorbs B into A's session.
    run3 = ScrapeRun(status="success")
    session.add(run3)
    session.flush()
    session.add_all([
        _obs(item.id, run3.id, "B", t1 + timedelta(minutes=30), qty=100),
        _obs(item.id, run3.id, "B", t2, qty=100),
    ])
    session.commit()

    sync_my_listing_sessions(session, item.id)
    session.commit()

    b_session = session.query(MyListingSession).filter_by(tracked_item_id=item.id, ssi="B").first()
    assert b_session is not None
    assert b_session.total_quantity_sold == 0  # nothing sold in B yet
    assert b_session.ended_reason is None       # cleared so A can't re-trigger next cycle

    # CYCLE 3: the critical regression cycle. Without the fix, ended_reason was "shop_removed"
    # on the session, so A's raw compute result (sold_out_early=100) matched the continuation
    # query → total_qty_sold jumped to 100 on B.
    sync_my_listing_sessions(session, item.id)
    session.commit()

    b_session = session.query(MyListingSession).filter_by(tracked_item_id=item.id, ssi="B").first()
    assert b_session is not None
    assert b_session.total_quantity_sold == 0  # must not have absorbed A's 100 qty


def test_continuation_within_single_sync_does_not_double_count_when_new_ssi_iterated_first(session):
    """Regression: if compute_my_listing_sessions yields the NEW SSI before the OLD SSI in
    a single sync call, the old SSI result must be skipped (consumed_ssis guard), not used
    as yet another continuation target.
    """
    item = add_tracked_item(session, item_name="Elunium")
    add_vendor_alias(session, "MyAlt")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    t0 = datetime(2026, 6, 2, 10, 0)
    t1 = t0 + timedelta(hours=1)

    # Set up a shop_removed session for A manually (simulates state after first sync +
    # mark_shop_removed, without relying on sync to produce it).
    existing = MyListingSession(
        tracked_item_id=item.id,
        ssi="A",
        seller_name="MyAlt",
        shop_name="MyShop",
        map_name="prt_mk.gat",
        price=20000,
        window_start=t0,
        window_end=t0 + timedelta(hours=24),
        initial_quantity=100,
        last_known_quantity=100,
        total_quantity_sold=0,
        status="shop_removed",
        ended_reason="shop_removed",
    )
    session.add(existing)
    session.flush()

    # Both A (old, disappeared) and B (new relist) observations in same sync.
    session.add_all([
        _obs(item.id, run.id, "A", t0, qty=100),
        _obs(item.id, run.id, "B", t1, qty=100),  # t1: A gone, B new
        _obs(item.id, run.id, "B", t1 + timedelta(minutes=30), qty=100),
    ])
    session.commit()

    sync_my_listing_sessions(session, item.id)
    session.commit()

    sessions = session.query(MyListingSession).filter_by(tracked_item_id=item.id).all()
    assert len(sessions) == 1
    s = sessions[0]
    assert s.ssi == "B"
    assert s.total_quantity_sold == 0  # A had 0 real sales; B hasn't sold yet


def test_old_ssi_raw_obs_do_not_reverse_continuation_on_subsequent_syncs(session):
    """Regression: after a continuation (A→B), old SSI A raw observations must NOT trigger
    a backwards continuation that re-assigns B's session back to A and closes it.

    Root cause: without window_start < result.window_start in the continuation query, result
    "A" (old obs, window_start=t0) could match session B (window_start=t2) as a continuation
    target, reversing the SSI from B→A and closing the session with inflated qty. Meanwhile,
    result "B" lands in consumed_ssis and gets skipped, effectively dropping the active listing.
    """
    item = add_tracked_item(session, item_name="Elunium")
    add_vendor_alias(session, "MyAlt")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    t0 = datetime(2026, 6, 3, 10, 0)
    t1 = t0 + timedelta(hours=1)
    t2 = t1 + timedelta(hours=1)

    # Simulate state after a correct first continuation: session has ssi="B", ended_reason=None.
    # But imagine the old code left ended_reason="shop_removed" on the active session (bug).
    # We manually construct that state here.
    existing = MyListingSession(
        tracked_item_id=item.id,
        ssi="B",
        seller_name="MyAlt",
        shop_name="MyShop",
        map_name="prt_mk.gat",
        price=20000,
        window_start=t2,
        window_end=t2 + timedelta(hours=24),
        initial_quantity=100,
        last_known_quantity=100,
        total_quantity_sold=0,
        status="active",
        ended_reason="shop_removed",  # buggy state left by old code
    )
    session.add(existing)
    session.flush()

    # Raw obs: both old A (disappeared at t1) and current B (still active at t2).
    sentinel_run = ScrapeRun(status="success")
    session.add(sentinel_run)
    session.flush()
    session.add_all([
        _obs(item.id, run.id, "A", t0, qty=100),
        _obs(item.id, sentinel_run.id, "SENTINEL", t1, qty=5, seller="OtherSeller"),
        _obs(item.id, run.id, "B", t2, qty=100),
    ])
    session.commit()

    sync_my_listing_sessions(session, item.id)
    session.commit()

    sessions_all = session.query(MyListingSession).filter_by(tracked_item_id=item.id).all()
    # Session B must NOT have been reversed back to ssi A or closed.
    b_session = session.query(MyListingSession).filter_by(tracked_item_id=item.id, ssi="B").first()
    assert b_session is not None, "Session B must still exist and not be re-assigned to A"
    assert b_session.status == "active"
    assert b_session.total_quantity_sold == 0
