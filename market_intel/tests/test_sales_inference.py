from datetime import datetime, timedelta

from sales_inference import SELLOUT_GRACE_WINDOW_POLLS, compute_sale_events
from settings import settings

GRACE = timedelta(seconds=SELLOUT_GRACE_WINDOW_POLLS * settings.poll_interval_seconds)


def _obs(ssi, observed_at, qty, seller="Bob", map_name="prt_mk.gat", price=100):
    class Obs:
        pass

    o = Obs()
    o.ssi = ssi
    o.observed_at = observed_at
    o.quantity = qty
    o.seller_name = seller
    o.map_name = map_name
    o.price = price
    return o


def test_full_sellout_confirmed_after_grace_window_with_no_relist():
    long_ago = datetime.now() - GRACE - timedelta(hours=1)
    observations = [
        _obs("A", long_ago, 200, seller="Bob"),
        # A different, still-listed item from someone else, defining "latest_cycle_at" as now.
        _obs("Z", datetime.now(), 50, seller="Zara"),
    ]
    events = compute_sale_events(observations)
    matches = [e for e in events if e.sale_attributed_at == long_ago]
    assert len(matches) == 1
    assert matches[0].quantity_sold == 200
    assert matches[0].method == "sellout_no_relist"
    assert matches[0].relisted_ssi is None


def test_partial_relist_only_counts_shortfall():
    disappeared_at = datetime.now() - GRACE - timedelta(hours=1)
    relisted_at = disappeared_at + timedelta(minutes=10)
    observations = [
        _obs("A", disappeared_at, 200, seller="Alice"),
        _obs("A2", relisted_at, 80, seller="Alice"),  # same seller, new ssi, smaller qty
        _obs("Z", datetime.now(), 50, seller="Zara"),
    ]
    events = compute_sale_events(observations)
    matches = [e for e in events if e.sale_attributed_at == disappeared_at]
    assert len(matches) == 1
    assert matches[0].quantity_sold == 120  # 200 - 80, not the full 200
    assert matches[0].method == "sellout_partial_relist"
    assert matches[0].relisted_ssi == "A2"
    assert matches[0].relisted_quantity == 80


def test_relist_with_equal_or_higher_qty_counts_as_no_sale():
    disappeared_at = datetime.now() - GRACE - timedelta(hours=1)
    relisted_at = disappeared_at + timedelta(minutes=10)
    observations = [
        _obs("A", disappeared_at, 200, seller="Carol"),
        _obs("A2", relisted_at, 300, seller="Carol"),  # increase, not a partial sale
        _obs("Z", datetime.now(), 50, seller="Zara"),
    ]
    events = compute_sale_events(observations)
    assert [e for e in events if e.sale_attributed_at == disappeared_at] == []


def test_relist_after_grace_window_does_not_cancel_the_sale():
    disappeared_at = datetime.now() - GRACE - timedelta(hours=2)
    too_late_relist = disappeared_at + GRACE + timedelta(hours=1)
    observations = [
        _obs("A", disappeared_at, 200, seller="Dave"),
        _obs("A2", too_late_relist, 200, seller="Dave"),
        _obs("Z", datetime.now(), 50, seller="Zara"),
    ]
    events = compute_sale_events(observations)
    matches = [e for e in events if e.sale_attributed_at == disappeared_at]
    assert len(matches) == 1
    assert matches[0].quantity_sold == 200  # the relist was too late to count as a correction
    assert matches[0].method == "sellout_no_relist"


def test_still_listed_at_latest_cycle_is_not_treated_as_disappeared():
    now = datetime.now()
    observations = [
        _obs("A", now - timedelta(hours=1), 200, seller="Eve"),
        _obs("A", now, 200, seller="Eve"),  # same ssi, still present at the latest cycle
    ]
    assert compute_sale_events(observations) == []


def test_recent_disappearance_within_grace_window_is_pending_not_counted():
    recent = datetime.now() - timedelta(minutes=1)
    observations = [
        _obs("A", recent, 200, seller="Frank"),
        _obs("Z", datetime.now(), 50, seller="Zara"),
    ]
    assert compute_sale_events(observations) == []  # too soon to confirm -- might still be relisted


def test_disappearance_without_seller_name_is_not_counted():
    long_ago = datetime.now() - GRACE - timedelta(hours=1)
    observations = [
        _obs("A", long_ago, 200, seller=None),
        _obs("Z", datetime.now(), 50, seller="Zara"),
    ]
    assert compute_sale_events(observations) == []


def test_same_listing_decrease_is_recorded_with_method_decrease():
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 10, 0)
    observations = [
        _obs("A", t0, 300, seller="Greg"),
        _obs("A", t1, 250, seller="Greg"),
    ]
    events = compute_sale_events(observations)
    assert len(events) == 1
    assert events[0].quantity_sold == 50
    assert events[0].method == "decrease"
    assert events[0].sale_attributed_at == t1
