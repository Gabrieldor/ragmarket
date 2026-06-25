from datetime import datetime, timedelta

from sales_inference import compute_my_listing_sessions


def _obs(ssi, observed_at, qty, seller="MyAlt", shop="MyShop", map_name="prt_mk.gat", price=20000):
    class Obs:
        pass

    o = Obs()
    o.ssi = ssi
    o.observed_at = observed_at
    o.quantity = qty
    o.seller_name = seller
    o.shop_name = shop
    o.map_name = map_name
    o.price = price
    return o


def test_active_session_not_enough_time_passed():
    start = datetime(2026, 1, 5, 9, 0)
    my_obs = [_obs("A", start, 100)]
    all_obs = [_obs("A", start, 100), _obs("OTHER", start, 5, seller="Someone")]
    sessions = compute_my_listing_sessions(my_obs, all_obs, window_hours=24)
    assert len(sessions) == 1
    assert sessions[0].status == "active"
    assert sessions[0].total_quantity_sold == 0


def test_decrease_while_still_listed_is_a_confirmed_sale_chunk():
    start = datetime(2026, 1, 5, 9, 0)
    later = start + timedelta(hours=2)
    my_obs = [_obs("A", start, 100), _obs("A", later, 60)]
    all_obs = my_obs + [_obs("OTHER", later, 5, seller="Someone")]
    sessions = compute_my_listing_sessions(my_obs, all_obs, window_hours=24)
    s = sessions[0]
    assert s.status == "active"  # window (24h) hasn't elapsed yet
    assert s.total_quantity_sold == 40
    assert s.sale_chunks == [(later, 40)]


def test_sold_out_early_counts_remainder():
    start = datetime(2026, 1, 5, 9, 0)
    last_seen = start + timedelta(hours=2)
    confirming_scrape = start + timedelta(hours=10)  # within the window, after last_seen
    my_obs = [_obs("A", start, 100), _obs("A", last_seen, 60)]
    # 'A' is absent from this later scrape (only "OTHER" present) -- proof of disappearance.
    all_obs = my_obs + [_obs("OTHER", confirming_scrape, 5, seller="Someone")]
    sessions = compute_my_listing_sessions(my_obs, all_obs, window_hours=24)
    s = sessions[0]
    assert s.status == "sold_out_early"
    assert s.total_quantity_sold == 100  # 40 (decrease) + 60 (remainder counted as sold)
    assert s.last_known_quantity == 60
    # The decrease (40) and the early-sellout remainder (60) both land at the same
    # timestamp here (the listing's last-seen quantity was itself a decrease) -- they must
    # merge into one chunk, not two separate entries at the same instant.
    assert s.sale_chunks == [(last_seen, 100)]


def test_sold_out_early_after_an_unchanged_observation_does_not_merge_incorrectly():
    """When the decrease and the final disappearance happen at *different* timestamps
    (an unchanged observation sits between them), they must stay as two separate chunks,
    not get merged just because they're both in the same session."""
    start = datetime(2026, 1, 5, 9, 0)
    decrease_at = start + timedelta(hours=1)
    unchanged_at = start + timedelta(hours=2)
    confirming_scrape = start + timedelta(hours=10)
    my_obs = [
        _obs("A", start, 100),
        _obs("A", decrease_at, 60),
        _obs("A", unchanged_at, 60),  # same qty, no new sale here
    ]
    all_obs = my_obs + [_obs("OTHER", confirming_scrape, 5, seller="Someone")]
    sessions = compute_my_listing_sessions(my_obs, all_obs, window_hours=24)
    s = sessions[0]
    assert s.status == "sold_out_early"
    assert s.total_quantity_sold == 100  # 40 decrease + 60 remainder
    assert s.sale_chunks == [(decrease_at, 40), (unchanged_at, 60)]


def test_expired_with_remainder_unsold_does_not_count_remainder():
    start = datetime(2026, 1, 5, 9, 0)
    last_seen = start + timedelta(hours=23)  # still listed near the end of the window
    after_window_scrape = start + timedelta(hours=25)  # confirms window_time_has_passed
    my_obs = [_obs("A", start, 100), _obs("A", last_seen, 60)]
    all_obs = my_obs + [_obs("OTHER", after_window_scrape, 5, seller="Someone")]
    sessions = compute_my_listing_sessions(my_obs, all_obs, window_hours=24)
    s = sessions[0]
    assert s.status == "expired"
    assert s.total_quantity_sold == 40  # only the observed decrease, not the remaining 60
    assert s.last_known_quantity == 60


def test_no_evidence_of_disappearance_within_window_stays_expired_not_sold_out():
    """If the window's time has passed but we never scraped again specifically within the
    window after last seeing it (e.g. only a scrape well past window_end exists), we can't
    distinguish early-sellout from "still there until expiry" -- defaults to expired."""
    start = datetime(2026, 1, 5, 9, 0)
    last_seen = start + timedelta(hours=2)
    far_future_scrape = start + timedelta(hours=48)  # after window_end, not within it
    my_obs = [_obs("A", start, 100), _obs("A", last_seen, 60)]
    all_obs = my_obs + [_obs("OTHER", far_future_scrape, 5, seller="Someone")]
    sessions = compute_my_listing_sessions(my_obs, all_obs, window_hours=24)
    s = sessions[0]
    assert s.status == "expired"
    assert s.total_quantity_sold == 40
