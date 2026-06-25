"""Low-stock ("sold out") detection, used by the collector to persist confirmed triggers
(see db.repository.infer_and_persist_sold_out) -- distinct from sales_inference.py, which
infers *completed sales* via disappearance/relist correction for the "Sellout Audit" page.
This module only watches a still-listed listing's own quantity against its own first-seen
baseline, with no notion of disappearance at all.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass
class InferredSoldOutTrigger:
    ssi: str
    seller_name: str | None
    shop_name: str | None
    map_name: str | None
    baseline_quantity: int
    quantity_at_trigger: int
    triggered_at: datetime  # the observed_at of the qualifying observation


def _overlaps_quiet_hours(
    prev_at: datetime, curr_at: datetime, quiet_start: str | None, quiet_end: str | None
) -> bool:
    """Whether the [prev_at, curr_at] gap overlaps the configured "HH:MM"-"HH:MM" quiet-hours
    window on any calendar day in that range. Supports overnight wraparound (e.g.
    start="23:00", end="06:00" spans into the next day). Disabled entirely if either bound
    is unset.
    """
    if not quiet_start or not quiet_end:
        return False
    start_t = time.fromisoformat(quiet_start)
    end_t = time.fromisoformat(quiet_end)

    day = prev_at.date() - timedelta(days=1)
    last_day = curr_at.date() + timedelta(days=1)
    while day <= last_day:
        window_start = datetime.combine(day, start_t)
        window_end = datetime.combine(day, end_t)
        if end_t <= start_t:
            window_end += timedelta(days=1)
        if window_start < curr_at and window_end > prev_at:
            return True
        day += timedelta(days=1)
    return False


def compute_sold_out_triggers(
    observations: list,
    threshold_ratio: float,
    quiet_hours_start: str | None,
    quiet_hours_end: str | None,
    max_normal_gap_seconds: float | None = None,
) -> list[InferredSoldOutTrigger]:
    """Per listing (matched by its stable ``ssi``), compares each observation's quantity
    against the quantity of that listing's *first-ever* observation (the baseline). The
    first observation pair whose later quantity is at or below ``threshold_ratio`` of the
    baseline is the trigger -- at most one trigger per ssi, since quantities on a single
    listing only ever decrease in this game's vending model (a restock is a new ssi with
    its own fresh baseline, not a re-arming of this one).

    A qualifying pair is skipped (not yet confirmed, may still confirm on a later pair) if
    the gap between the two observations is *abnormally long* (longer than
    ``max_normal_gap_seconds``, e.g. the collector was offline overnight) *and* that gap
    overlaps the configured quiet-hours window. The gap-length check matters: without it,
    every pair that merely happens to fall on the clock during quiet hours would be
    suppressed even on a normal, uninterrupted poll cadence (PC left on overnight) --
    quiet hours should only cover for actual downtime, not interfere when nothing was
    actually offline. If ``max_normal_gap_seconds`` is None, any clock-overlap suppresses
    (no gap-length distinction).

    ``observations`` accepts anything with ``.ssi``, ``.observed_at``, ``.quantity``,
    ``.seller_name``, ``.shop_name``, ``.map_name`` attributes -- ORM rows or plain test
    doubles alike.
    """
    by_ssi: dict[str, list] = defaultdict(list)
    for obs in observations:
        if obs.ssi:
            by_ssi[obs.ssi].append(obs)
    for obs_list in by_ssi.values():
        obs_list.sort(key=lambda o: o.observed_at)

    triggers: list[InferredSoldOutTrigger] = []
    for ssi, obs_list in by_ssi.items():
        baseline = obs_list[0].quantity
        if baseline <= 0:
            continue
        threshold = threshold_ratio * baseline

        for prev, curr in zip(obs_list, obs_list[1:]):
            if curr.quantity > threshold:
                continue
            gap_seconds = (curr.observed_at - prev.observed_at).total_seconds()
            is_abnormal_gap = max_normal_gap_seconds is None or gap_seconds > max_normal_gap_seconds
            if is_abnormal_gap and _overlaps_quiet_hours(
                prev.observed_at, curr.observed_at, quiet_hours_start, quiet_hours_end
            ):
                continue
            triggers.append(
                InferredSoldOutTrigger(
                    ssi=ssi,
                    seller_name=curr.seller_name or prev.seller_name,
                    shop_name=curr.shop_name or prev.shop_name,
                    map_name=curr.map_name or prev.map_name,
                    baseline_quantity=baseline,
                    quantity_at_trigger=curr.quantity,
                    triggered_at=curr.observed_at,
                )
            )
            break

    return triggers
