from datetime import datetime, timedelta

from sold_out_inference import compute_sold_out_triggers


def _obs(ssi, observed_at, qty, seller="Bob", shop="Bob's Shop", map_name="prt_mk.gat"):
    class Obs:
        pass

    o = Obs()
    o.ssi = ssi
    o.observed_at = observed_at
    o.quantity = qty
    o.seller_name = seller
    o.shop_name = shop
    o.map_name = map_name
    return o


def test_triggers_once_quantity_drops_to_threshold_of_baseline():
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 9, 10)
    observations = [_obs("A", t0, 100), _obs("A", t1, 10)]  # 10% of baseline
    triggers = compute_sold_out_triggers(observations, threshold_ratio=0.10, quiet_hours_start=None, quiet_hours_end=None)
    assert len(triggers) == 1
    assert triggers[0].ssi == "A"
    assert triggers[0].baseline_quantity == 100
    assert triggers[0].quantity_at_trigger == 10
    assert triggers[0].triggered_at == t1


def test_no_trigger_above_threshold():
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 9, 10)
    observations = [_obs("A", t0, 100), _obs("A", t1, 50)]
    assert compute_sold_out_triggers(observations, 0.10, None, None) == []


def test_zero_baseline_never_triggers():
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 9, 10)
    observations = [_obs("A", t0, 0), _obs("A", t1, 0)]
    assert compute_sold_out_triggers(observations, 0.10, None, None) == []


def test_one_trigger_per_ssi_even_if_it_keeps_dropping():
    t0 = datetime(2026, 1, 5, 9, 0)
    t1 = datetime(2026, 1, 5, 9, 10)
    t2 = datetime(2026, 1, 5, 9, 20)
    observations = [_obs("A", t0, 100), _obs("A", t1, 8), _obs("A", t2, 2)]
    triggers = compute_sold_out_triggers(observations, 0.10, None, None)
    assert len(triggers) == 1
    assert triggers[0].triggered_at == t1


def test_quiet_hours_gap_skips_then_later_pair_confirms():
    # t0 -> t1 spans the 00:00-06:00 quiet window -- should not trigger yet even though
    # quantity is already low by t1. t1 -> t2 is entirely after the window closes, so that
    # pair is free to confirm it.
    t0 = datetime(2026, 1, 5, 23, 0)
    t1 = datetime(2026, 1, 6, 6, 30)
    t2 = datetime(2026, 1, 6, 7, 0)
    observations = [_obs("A", t0, 100), _obs("A", t1, 5), _obs("A", t2, 5)]
    triggers = compute_sold_out_triggers(observations, 0.10, quiet_hours_start="00:00", quiet_hours_end="06:00")
    assert len(triggers) == 1
    assert triggers[0].triggered_at == t2


def test_quiet_hours_disabled_when_either_bound_missing():
    t0 = datetime(2026, 1, 5, 23, 0)
    t1 = datetime(2026, 1, 6, 5, 0)
    observations = [_obs("A", t0, 100), _obs("A", t1, 5)]
    triggers = compute_sold_out_triggers(observations, 0.10, quiet_hours_start="00:00", quiet_hours_end=None)
    assert len(triggers) == 1
    assert triggers[0].triggered_at == t1


def test_gap_entirely_outside_quiet_hours_still_triggers():
    t0 = datetime(2026, 1, 5, 12, 0)
    t1 = datetime(2026, 1, 5, 12, 10)
    observations = [_obs("A", t0, 100), _obs("A", t1, 5)]
    triggers = compute_sold_out_triggers(observations, 0.10, quiet_hours_start="00:00", quiet_hours_end="06:00")
    assert len(triggers) == 1


def test_normal_cadence_gap_within_quiet_hours_is_not_suppressed_when_max_gap_given():
    # PC stayed on -- a normal ~10min poll gap that happens to land at 2am should NOT be
    # suppressed just because the clock is inside quiet hours, when a max_normal_gap_seconds
    # is given (only abnormally long gaps should defer to quiet hours).
    t0 = datetime(2026, 1, 6, 1, 50)
    t1 = datetime(2026, 1, 6, 2, 0)
    observations = [_obs("A", t0, 100), _obs("A", t1, 5)]
    triggers = compute_sold_out_triggers(
        observations, 0.10, quiet_hours_start="00:00", quiet_hours_end="06:00",
        max_normal_gap_seconds=600 * 2,
    )
    assert len(triggers) == 1
    assert triggers[0].triggered_at == t1


def test_abnormally_long_gap_within_quiet_hours_is_still_suppressed_when_max_gap_given():
    # A multi-hour gap (PC actually off) overlapping quiet hours should still be deferred.
    t0 = datetime(2026, 1, 5, 23, 0)
    t1 = datetime(2026, 1, 6, 5, 0)
    observations = [_obs("A", t0, 100), _obs("A", t1, 5)]
    triggers = compute_sold_out_triggers(
        observations, 0.10, quiet_hours_start="00:00", quiet_hours_end="06:00",
        max_normal_gap_seconds=600 * 2,
    )
    assert triggers == []
