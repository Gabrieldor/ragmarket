from datetime import datetime, timedelta

from db.models import ListingObservation, ScrapeRun
from db.repository import add_tracked_item, add_vendor_alias, set_item_cost_basis, sync_my_listing_sessions


def test_alias_crud(client):
    resp = client.post("/my-sales/aliases", json={"alias_name": "MyAlt"})
    assert resp.status_code == 201
    alias_id = resp.json()["id"]

    resp = client.get("/my-sales/aliases")
    assert len(resp.json()) == 1
    assert resp.json()[0]["alias_name"] == "MyAlt"

    resp = client.delete(f"/my-sales/aliases/{alias_id}")
    assert resp.status_code == 204
    assert client.get("/my-sales/aliases").json() == []


def test_alias_duplicate_rejected(client):
    client.post("/my-sales/aliases", json={"alias_name": "MyAlt"})
    resp = client.post("/my-sales/aliases", json={"alias_name": "MyAlt"})
    assert resp.status_code == 400


def test_cost_basis_set_and_get(client):
    item_resp = client.post("/items", json={"item_name": "Elunium"})
    item_id = item_resp.json()["id"]

    assert client.get(f"/my-sales/cost-basis/{item_id}").json() is None

    resp = client.post(f"/my-sales/cost-basis/{item_id}", json={"cost_per_unit": 1000})
    assert resp.status_code == 201
    assert resp.json()["cost_per_unit"] == 1000

    # Updating again returns the new value without erroring -- history is preserved
    # server-side, but the "current" read always reflects the latest.
    client.post(f"/my-sales/cost-basis/{item_id}", json={"cost_per_unit": 1500})
    assert client.get(f"/my-sales/cost-basis/{item_id}").json()["cost_per_unit"] == 1500


def test_sessions_and_summary_reflect_revenue_and_profit(session, client):
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
    sync_my_listing_sessions(session, item.id)
    session.commit()

    resp = client.get("/my-sales/sessions")
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["total_quantity_sold"] == 40
    assert rows[0]["revenue"] == 40 * 20000
    assert rows[0]["profit"] == 40 * 20000 - 40 * 1000

    resp = client.get("/my-sales/summary")
    body = resp.json()
    assert body["total_quantity_sold"] == 40
    assert body["total_revenue"] == 800000
    assert body["total_profit"] == 800000 - 40000
    assert len(body["by_item"]) == 1
    assert body["by_item"][0]["item_name"] == "Elunium"
    assert len(body["by_map"]) == 1
    assert body["by_map"][0]["map_name"] == "prt_mk.gat"
    assert any(h["hour"] == t1.hour and h["quantity_sold"] == 40 for h in body["by_hour"])


def test_summary_profit_is_null_when_cost_basis_missing(session, client):
    item = add_tracked_item(session, item_name="Elunium")
    add_vendor_alias(session, "MyAlt")
    run = ScrapeRun(status="success")
    session.add(run)
    session.flush()
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = t0 + timedelta(hours=1)
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
    sync_my_listing_sessions(session, item.id)
    session.commit()

    resp = client.get("/my-sales/summary")
    body = resp.json()
    assert body["total_profit"] is None
    assert body["by_item"][0]["profit"] is None
