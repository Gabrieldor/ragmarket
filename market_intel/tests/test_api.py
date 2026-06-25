from datetime import datetime, timedelta

from db.models import CollectorStatus, DailyStat, ListingObservation, MapStat, ScrapeRun
from db.repository import add_tracked_item, infer_and_persist_sales, infer_and_persist_sold_out


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_and_list_items(client):
    resp = client.post("/items", json={"item_name": "Elunium", "server_name": "FREYA", "store_type": "BUY"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["item_name"] == "Elunium"
    assert body["is_active"] is True

    resp = client.get("/items")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_update_item_toggles_active(client):
    created = client.post("/items", json={"item_name": "Elunium"}).json()
    item_id = created["id"]

    resp = client.patch(f"/items/{item_id}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    resp = client.get("/items?active_only=true")
    assert resp.json() == []


def test_update_missing_item_404(client):
    resp = client.patch("/items/999", json={"is_active": False})
    assert resp.status_code == 404


def test_update_item_toggles_sold_out_enabled(client):
    created = client.post("/items", json={"item_name": "Elunium"}).json()
    assert created["sold_out_enabled"] is True
    item_id = created["id"]

    resp = client.patch(f"/items/{item_id}", json={"sold_out_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["sold_out_enabled"] is False


def test_observations_filter_by_item(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    session.add(
        ListingObservation(
            tracked_item_id=item.id,
            scrape_run_id=run.id,
            observed_at=datetime(2026, 1, 5, 10, 0),
            price=100,
            quantity=5,
            seller_name="Sicarius.",
        )
    )
    session.commit()

    resp = client.get(f"/observations?tracked_item_id={item.id}")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["seller_name"] == "Sicarius."


def test_weekend_vs_weekday_endpoint(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    session.add_all([
        DailyStat(
            tracked_item_id=item.id, date="2026-01-05", weekday=0, is_weekend=False,
            avg_price=100, median_price=100, min_price=100, max_price=100,
            total_quantity=10, listing_count=5,
        ),
        DailyStat(
            tracked_item_id=item.id, date="2026-01-10", weekday=5, is_weekend=True,
            avg_price=150, median_price=150, min_price=150, max_price=150,
            total_quantity=10, listing_count=5,
        ),
    ])
    session.commit()

    resp = client.get(f"/analytics/{item.id}/weekend-vs-weekday")
    assert resp.status_code == 200
    body = resp.json()
    assert body["weekday_avg_price"] == 100
    assert body["weekend_avg_price"] == 150
    assert body["percent_difference"] == 50.0


def test_trend_endpoint_no_data_returns_nulls(client):
    resp = client.post("/items", json={"item_name": "Elunium"})
    item_id = resp.json()["id"]

    resp = client.get(f"/analytics/{item_id}/trend?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recent_avg_price"] is None
    assert body["percent_change"] is None


def test_collector_status_offline_when_no_row(client):
    resp = client.get("/collector/status")
    assert resp.status_code == 200
    assert resp.json()["state"] == "offline"


def test_collector_status_reflects_fresh_heartbeat(session, client):
    session.add(
        CollectorStatus(
            id=1, state="scraping", current_item_name="Elunium",
            updated_at=datetime.now(),
        )
    )
    session.commit()

    resp = client.get("/collector/status")
    body = resp.json()
    assert body["state"] == "scraping"
    assert body["current_item_name"] == "Elunium"


def test_collector_status_offline_when_heartbeat_stale(session, client):
    session.add(
        CollectorStatus(
            id=1, state="scraping", current_item_name="Elunium",
            updated_at=datetime.now() - timedelta(hours=2),
        )
    )
    session.commit()

    resp = client.get("/collector/status")
    assert resp.json()["state"] == "offline"


def test_collector_status_long_rate_limit_sleep_not_treated_as_offline(session, client):
    """Regression test: a multi-hour rate-limit backoff sleep has no heartbeat update
    for hours by design -- staleness must be judged against next_cycle_at, not a short
    fixed window, or a perfectly healthy long sleep gets misreported as offline.
    """
    session.add(
        CollectorStatus(
            id=1, state="rate_limited", current_item_name=None,
            next_cycle_at=datetime.now() + timedelta(hours=1, minutes=30),
            consecutive_rate_limits=2,
            updated_at=datetime.now() - timedelta(minutes=20),  # well past the old 11min threshold
        )
    )
    session.commit()

    resp = client.get("/collector/status")
    body = resp.json()
    assert body["state"] == "rate_limited"
    assert body["consecutive_rate_limits"] == 2


def test_collector_status_offline_once_next_cycle_time_passes_with_no_update(session, client):
    session.add(
        CollectorStatus(
            id=1, state="rate_limited", current_item_name=None,
            next_cycle_at=datetime.now() - timedelta(minutes=10),  # should have woken up by now
            consecutive_rate_limits=2,
            updated_at=datetime.now() - timedelta(hours=1, minutes=30),
        )
    )
    session.commit()

    resp = client.get("/collector/status")
    assert resp.json()["state"] == "offline"


def test_current_snapshot_no_data_returns_zeros(client):
    resp = client.post("/items", json={"item_name": "Elunium"})
    item_id = resp.json()["id"]

    resp = client.get(f"/analytics/{item_id}/current")
    assert resp.status_code == 200
    body = resp.json()
    assert body["observed_at"] is None
    assert body["listing_count"] == 0
    assert body["total_quantity"] == 0
    assert body["avg_price"] is None


def test_current_snapshot_uses_only_latest_cycle(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    older = datetime(2026, 1, 1, 10, 0)
    latest = datetime(2026, 1, 2, 10, 0)
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, observed_at=older,
            price=999, quantity=999,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, observed_at=latest,
            price=100, quantity=10,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, observed_at=latest,
            price=200, quantity=20,
        ),
    ])
    session.commit()

    resp = client.get(f"/analytics/{item.id}/current")
    body = resp.json()
    assert body["listing_count"] == 2  # only the 2 rows from the latest cycle, not the older one
    assert body["total_quantity"] == 30
    assert body["avg_price"] == 150
    assert body["min_price"] == 100
    assert body["max_price"] == 200


def test_sales_by_hour_infers_from_quantity_decrease(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    # Same listing (ssi="A"): 300 -> 250 -> 250 (no change) -> 100. Two sale events:
    # 50 sold at hour 10, 150 sold at hour 12. The unchanged 250->250 step is not a sale.
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=300,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 10, 0), price=100, quantity=250,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 11, 0), price=100, quantity=250,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 12, 0), price=100, quantity=100,
        ),
        # A different listing (ssi="B") that *increases* in quantity (restock) -- not a sale.
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=datetime(2026, 1, 5, 9, 0), price=200, quantity=10,
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=datetime(2026, 1, 5, 10, 0), price=200, quantity=20,
        ),
    ])
    session.commit()
    infer_and_persist_sales(session, item.id)  # collector does this after each scrape
    session.commit()

    resp = client.get(f"/analytics/{item.id}/sales-by-hour")
    assert resp.status_code == 200
    by_hour = {row["hour"]: row for row in resp.json()}

    assert by_hour[10]["estimated_units_sold"] == 50
    assert by_hour[10]["sale_events"] == 1
    assert by_hour[12]["estimated_units_sold"] == 150
    assert 11 not in by_hour  # no decrease happened at hour 11
    assert 9 not in by_hour  # first observation of each ssi has nothing to compare against


def test_sales_by_hour_map_breaks_down_per_map(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    session.add_all([
        # Map A: 300 -> 250 at hour 10 (50 sold).
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=300, map_name="prt_mk.gat",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 10, 0), price=100, quantity=250, map_name="prt_mk.gat",
        ),
        # Map B: 100 -> 60 at hour 10 too (40 sold) -- same hour, different map.
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=100, map_name="prt_in.gat",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=datetime(2026, 1, 5, 10, 0), price=100, quantity=60, map_name="prt_in.gat",
        ),
    ])
    session.commit()
    infer_and_persist_sales(session, item.id)
    session.commit()

    resp = client.get(f"/analytics/{item.id}/sales-by-hour-map")
    assert resp.status_code == 200
    rows = {(r["map_name"], r["hour"]): r["estimated_units_sold"] for r in resp.json()}
    assert rows[("prt_mk.gat", 10)] == 50
    assert rows[("prt_in.gat", 10)] == 40


def test_map_alias_crud(client):
    resp = client.post(
        "/map-aliases", json={"canonical_name": "Abyss", "raw_map_names": ["abyss_03", "abyss_04"]}
    )
    assert resp.status_code == 201
    rows = resp.json()
    assert len(rows) == 2
    assert {r["raw_map_name"] for r in rows} == {"abyss_03", "abyss_04"}
    assert all(r["canonical_name"] == "Abyss" for r in rows)

    resp = client.get("/map-aliases")
    assert len(resp.json()) == 2

    alias_id = rows[0]["id"]
    resp = client.delete(f"/map-aliases/{alias_id}")
    assert resp.status_code == 204
    assert len(client.get("/map-aliases").json()) == 1


def test_map_alias_regroups_on_readd(client):
    client.post("/map-aliases", json={"canonical_name": "Abyss", "raw_map_names": ["abyss_03"]})
    resp = client.post("/map-aliases", json={"canonical_name": "Renamed Abyss", "raw_map_names": ["abyss_03"]})
    assert resp.status_code == 201
    assert resp.json()[0]["canonical_name"] == "Renamed Abyss"
    assert len(client.get("/map-aliases").json()) == 1  # upserted, not duplicated


def test_map_analysis_merges_aliased_maps(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=100,
            map_name="abyss_03",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=datetime(2026, 1, 5, 9, 0), price=200, quantity=50,
            map_name="abyss_04",
        ),
    ])
    session.add_all([
        MapStat(
            tracked_item_id=item.id, map_name="abyss_03",
            period_start="2026-01-05", period_end="2026-01-05",
            avg_price=100, listing_count=1, total_quantity=100,
        ),
        MapStat(
            tracked_item_id=item.id, map_name="abyss_04",
            period_start="2026-01-05", period_end="2026-01-05",
            avg_price=200, listing_count=1, total_quantity=50,
        ),
    ])
    session.commit()
    client.post("/map-aliases", json={"canonical_name": "Abyss", "raw_map_names": ["abyss_03", "abyss_04"]})

    resp = client.get(f"/analytics/{item.id}/map")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1  # merged into a single "Abyss" entry, not two separate rows
    assert body[0]["map_name"] == "Abyss"
    assert body[0]["listing_count"] == 2
    assert body[0]["total_quantity"] == 150
    # Regression: raw observations are stored under the original names, never the
    # canonical "Abyss" -- the dashboard's "View listings" needs these to query them.
    assert body[0]["raw_map_names"] == ["abyss_03", "abyss_04"]


def test_map_analysis_includes_estimated_units_sold(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=100,
            map_name="prt_mk.gat",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 10, 0), price=100, quantity=60,
            map_name="prt_mk.gat",
        ),
    ])
    session.add(
        MapStat(
            tracked_item_id=item.id, map_name="prt_mk.gat",
            period_start="2026-01-05", period_end="2026-01-05",
            avg_price=100, listing_count=2, total_quantity=160,
        )
    )
    session.commit()
    infer_and_persist_sales(session, item.id)  # collector does this after each scrape
    session.commit()

    resp = client.get(f"/analytics/{item.id}/map")
    body = resp.json()
    assert len(body) == 1
    assert body[0]["estimated_units_sold"] == 40
    assert body[0]["total_quantity"] == 160


def test_sellers_total_quantity_dedupes_repeated_polls_of_same_listing(session, client):
    """Regression test: a still-listed stall observed across many poll cycles must report
    its current stock once, not the sum of every poll's snapshot of the same quantity.
    """
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    # Same listing (ssi="A"), same seller, observed at 3 separate poll cycles with a
    # roughly-stable quantity -- naive summation would report ~3x the real stock.
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 0), price=100, quantity=277, seller_name="TDMerch1",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 10), price=100, quantity=277, seller_name="TDMerch1",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=datetime(2026, 1, 5, 9, 20), price=100, quantity=277, seller_name="TDMerch1",
        ),
    ])
    session.commit()

    resp = client.get(f"/analytics/{item.id}/sellers")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["seller_name"] == "TDMerch1"
    assert body[0]["total_quantity"] == 277  # not 831 (277 * 3)
    assert body[0]["listing_count"] == 3  # row count is unaffected, still reflects poll history


def test_sellers_total_quantity_sums_distinct_listings_for_same_seller(session, client):
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
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="B",
            observed_at=datetime(2026, 1, 5, 9, 0), price=110, quantity=50, seller_name="Bob",
        ),
    ])
    session.commit()

    resp = client.get(f"/analytics/{item.id}/sellers")
    body = resp.json()
    assert body[0]["total_quantity"] == 150  # two distinct listings, summed once each


def test_sellers_total_quantity_excludes_old_relisted_stock_not_in_latest_cycle(session, client):
    """Regression test: a seller who sold out an old listing and relisted under a new ssi
    must only count the current relist's quantity, not both the old (now-gone) listing and
    the new one -- total_quantity reflects what's for sale right now, not every distinct
    listing this seller has ever posted historically.
    """
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    old_cycle = datetime(2026, 1, 1, 9, 0)
    latest_cycle = datetime(2026, 1, 5, 9, 0)
    session.add_all([
        # Old listing, sold out -- no longer present at the latest cycle.
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="OLD",
            observed_at=old_cycle, price=100, quantity=500, seller_name="TDMerch1",
        ),
        # A different listing from the same seller, scraped repeatedly while still up.
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="NEW",
            observed_at=old_cycle, price=100, quantity=277, seller_name="TDMerch1",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="NEW",
            observed_at=latest_cycle, price=100, quantity=277, seller_name="TDMerch1",
        ),
    ])
    session.commit()

    resp = client.get(f"/analytics/{item.id}/sellers")
    body = resp.json()
    assert body[0]["seller_name"] == "TDMerch1"
    assert body[0]["total_quantity"] == 277  # not 777 (500 old + 277 current)


def test_sellers_excludes_sellers_with_zero_current_quantity(session, client):
    """A seller whose only listing has sold out / fallen off the latest cycle should not
    appear in the table at all -- it's a current-stock view, not a historical roster.
    """
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    old_cycle = datetime(2026, 1, 1, 9, 0)
    latest_cycle = datetime(2026, 1, 5, 9, 0)
    session.add_all([
        # Gone -- only ever observed in an old cycle, not the latest one.
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="GONE",
            observed_at=old_cycle, price=100, quantity=500, seller_name="SoldOutSeller",
        ),
        # Still around, to anchor latest_observed_at and give the endpoint data to return.
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="STILL_HERE",
            observed_at=latest_cycle, price=100, quantity=10, seller_name="StillHereSeller",
        ),
    ])
    session.commit()

    resp = client.get(f"/analytics/{item.id}/sellers")
    body = resp.json()
    names = {row["seller_name"] for row in body}
    assert "SoldOutSeller" not in names
    assert "StillHereSeller" in names


def test_listing_history_reports_lifecycle_and_quantity_sold(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()

    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 10, 0)
    t2 = datetime(2026, 1, 5, 11, 0)  # latest cycle overall
    session.add_all([
        # Still-active listing with a confirmed quantity decrease (a sale).
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="ACTIVE",
            observed_at=t0, price=100, quantity=300, seller_name="Greg", map_name="prt_mk.gat",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="ACTIVE",
            observed_at=t2, price=100, quantity=250, seller_name="Greg", map_name="prt_mk.gat",
        ),
        # A different, older listing not present at the latest cycle -- "gone".
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="GONE",
            observed_at=t1, price=100, quantity=80, seller_name="Carol",
        ),
    ])
    session.commit()
    infer_and_persist_sales(session, item.id)  # collector does this after each scrape
    session.commit()

    resp = client.get(f"/analytics/{item.id}/listing-history")
    assert resp.status_code == 200
    by_ssi = {row["ssi"]: row for row in resp.json()}

    active = by_ssi["ACTIVE"]
    assert active["is_active"] is True
    assert active["initial_quantity"] == 300
    assert active["last_known_quantity"] == 250
    assert active["quantity_sold"] == 50  # the decrease, via the already-persisted SaleEvent
    assert active["seller_name"] == "Greg"

    gone = by_ssi["GONE"]
    assert gone["is_active"] is False
    assert gone["initial_quantity"] == 80
    assert gone["last_known_quantity"] == 80


def test_sold_out_config_get_returns_defaults(client):
    resp = client.get("/sold-out/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["threshold_ratio"] == 0.10
    assert body["quiet_hours_start"] == "00:00"
    assert body["quiet_hours_end"] == "06:00"


def test_sold_out_config_patch_round_trip(client):
    resp = client.patch(
        "/sold-out/config",
        json={"threshold_ratio": 0.2, "quiet_hours_start": "23:00", "quiet_hours_end": "07:00"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["threshold_ratio"] == 0.2
    assert body["quiet_hours_start"] == "23:00"
    assert body["quiet_hours_end"] == "07:00"

    resp = client.get("/sold-out/config")
    assert resp.json()["threshold_ratio"] == 0.2


def test_sold_out_config_patch_can_clear_quiet_hours(client):
    resp = client.patch("/sold-out/config", json={"clear_quiet_hours": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["quiet_hours_start"] is None
    assert body["quiet_hours_end"] is None


def test_sold_out_events_endpoint_filters_by_item(session, client):
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

    resp = client.get(f"/sold-out/events?tracked_item_id={item.id}")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["ssi"] == "A"
    assert rows[0]["quantity_at_trigger"] == 5


def test_sold_out_summary_only_counts_currently_listed(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 9, 10)
    session.add_all([
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t0, price=100, quantity=100, seller_name="Bob",
        ),
        ListingObservation(
            tracked_item_id=item.id, scrape_run_id=run.id, ssi="A",
            observed_at=t1, price=100, quantity=5, seller_name="Bob",
        ),
    ])
    session.commit()
    infer_and_persist_sold_out(session, item.id)
    session.commit()

    resp = client.get("/sold-out/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body == [{"tracked_item_id": item.id, "active_count": 1}]


def test_create_watch_rule_parses_and_lists(client):
    resp = client.post("/watch-rules", json={"raw": "Elunium > 30k"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["item_name"] == "Elunium"
    assert body["operator"] == ">"
    assert body["target_price"] == 30000
    assert body["is_active"] is True
    assert body["state_active"] is False

    resp = client.get("/watch-rules")
    assert len(resp.json()) == 1


def test_create_watch_rule_invalid_format_400(client):
    resp = client.post("/watch-rules", json={"raw": "not a rule"})
    assert resp.status_code == 400


def test_create_watch_rule_duplicate_400(client):
    client.post("/watch-rules", json={"raw": "Elunium > 30000"})
    resp = client.post("/watch-rules", json={"raw": "Elunium > 30000"})
    assert resp.status_code == 400


def test_update_watch_rule_toggles_active(client):
    created = client.post("/watch-rules", json={"raw": "Elunium > 30000"}).json()
    resp = client.patch(f"/watch-rules/{created['id']}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_update_missing_watch_rule_404(client):
    resp = client.patch("/watch-rules/999", json={"is_active": False})
    assert resp.status_code == 404


def test_delete_watch_rule(client):
    created = client.post("/watch-rules", json={"raw": "Elunium > 30000"}).json()
    resp = client.delete(f"/watch-rules/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/watch-rules").json() == []


def test_delete_missing_watch_rule_404(client):
    resp = client.delete("/watch-rules/999")
    assert resp.status_code == 404


def test_notification_settings_get_returns_defaults(client):
    resp = client.get("/notifications/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["local_sound"] is True
    assert body["variance_percent"] == 1.0
    assert body["discord_token_masked"] is None


def test_notification_settings_patch_masks_token(client):
    resp = client.patch(
        "/notifications/settings",
        json={"discord_token": "supersecrettoken1234", "local_sound": False, "channel_id": "999"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["discord_token_masked"] == "...1234"
    assert body["local_sound"] is False
    assert body["channel_id"] == "999"


def test_notification_events_endpoint_filters_by_rule(session, client):
    from notifications.checker import check_watch_rules

    rule = client.post("/watch-rules", json={"raw": "Elunium > 1000"}).json()
    from db.models import WatchRule as WatchRuleModel

    row = session.get(WatchRuleModel, rule["id"])

    class _Listing:
        def __init__(self, price, quantity):
            self.price = price
            self.quantity = quantity

    class _FakeProvider:
        async def get_listings(self, item_name, store_type, server_type, sort, max_pages):
            return [_Listing(1100, 5)]

    class _FakeNotifier:
        async def send_triggered(self, rule, price):
            pass

    import asyncio

    from db.repository import get_notification_settings
    config = get_notification_settings(session)
    asyncio.run(check_watch_rules(session, _FakeProvider(), _FakeNotifier(), config))
    session.commit()

    resp = client.get(f"/notifications/events?watch_rule_id={row.id}")
    assert resp.status_code == 200
    events = resp.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "triggered"
    assert events[0]["price"] == 1100
