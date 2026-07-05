"""Shared sales-inference logic, used by both the API (for live computation/back-compat)
and the collector (which persists confirmed events -- see db.repository.record_sale_events
and CHECKLIST.md for why: a live-only computation gives no audit trail to later validate
this metric against real data).

compute_sale_events: global market sales, inferred from any seller's listings.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from settings import settings

# How many poll intervals to wait after a listing disappears before confirming it as fully
# sold out, rather than a delisting that's about to be relisted by the same seller.
SELLOUT_GRACE_WINDOW_POLLS = 3


@dataclass
class InferredSaleEvent:
    ssi: str
    seller_name: str | None
    map_name: str | None
    quantity_sold: int
    sale_attributed_at: datetime  # the observed_at this event is bucketed/dated by
    method: str  # 'decrease' | 'sellout_no_relist' | 'sellout_partial_relist'
    price: int | None = None  # listing price at the moment the sale was detected
    relisted_ssi: str | None = None
    relisted_quantity: int | None = None


def compute_sale_events(observations: list) -> list[InferredSaleEvent]:
    """Infers sales from two signals, combined:

    1. Same listing (matched by its stable ``ssi``) shows a quantity decrease across
       consecutive scrapes -- still listed, just smaller. Recorded as method='decrease'.
    2. A listing disappears entirely (sold out) -- confirmed only after a grace window
       (``SELLOUT_GRACE_WINDOW_POLLS`` poll intervals) has passed with no matching relist
       appearing. A relist is a *different* ssi from the *same seller* within that window.
       If one appears, only the shortfall (original qty minus relisted qty, floored at 0)
       counts as sold (method='sellout_partial_relist') -- e.g. 200 disappears, same seller
       relists 80, only 120 counts, avoiding overcounting when stock is partially sold and
       the remainder relisted under a new shop. If the relisted quantity is equal or higher
       (a restock, not a partial sale), nothing is recorded for that disappearance. With no
       relist at all, the full quantity counts (method='sellout_no_relist').

    Restocks on a still-listed item (quantity increases without disappearing) are never
    counted as negative sales, just ignored.

    ``observations`` accepts anything with ``.ssi``, ``.observed_at``, ``.quantity``,
    ``.seller_name``, ``.map_name`` attributes -- ORM rows or plain test doubles alike.

    Caveat (inherent to this method, not fixable by more code): items with very high
    listing turnover can see listings churn off the visible results purely from market
    competition (new cheaper listings appearing), not an actual sale. A disappearance is
    still just an inference, not a confirmed sale -- this is why events are persisted with
    enough detail (ssi, seller, relist info) to audit against real data later, rather than
    only ever existing as a live-recomputed number.
    """
    by_ssi: dict[str, list] = defaultdict(list)
    for obs in observations:
        if obs.ssi:
            by_ssi[obs.ssi].append(obs)
    for obs_list in by_ssi.values():
        obs_list.sort(key=lambda o: o.observed_at)

    events: list[InferredSaleEvent] = []

    # 1. Same-listing decreases.
    for ssi, obs_list in by_ssi.items():
        for prev, curr in zip(obs_list, obs_list[1:]):
            if curr.quantity < prev.quantity:
                events.append(
                    InferredSaleEvent(
                        ssi=ssi,
                        seller_name=curr.seller_name or prev.seller_name,
                        map_name=curr.map_name or prev.map_name,
                        quantity_sold=prev.quantity - curr.quantity,
                        sale_attributed_at=curr.observed_at,
                        method="decrease",
                        price=curr.price,
                    )
                )

    # 2. Disappearances, with relist correction.
    if not observations:
        return events

    latest_cycle_at = max(o.observed_at for o in observations)
    grace_window = timedelta(seconds=SELLOUT_GRACE_WINDOW_POLLS * settings.poll_interval_seconds)
    now = datetime.now()

    by_seller_chrono: dict[str, list] = defaultdict(list)
    for obs in sorted(observations, key=lambda o: o.observed_at):
        if obs.seller_name:
            by_seller_chrono[obs.seller_name].append(obs)

    for ssi, obs_list in by_ssi.items():
        last_obs = obs_list[-1]
        if last_obs.observed_at >= latest_cycle_at:
            continue  # still listed as of the most recent cycle -- not disappeared
        if not last_obs.seller_name:
            continue  # can't look for a relist without a seller to match on

        confirm_after = last_obs.observed_at + grace_window
        if now < confirm_after:
            continue  # grace window hasn't elapsed yet -- pending, don't count either way

        relisted_obs = None
        for candidate in by_seller_chrono.get(last_obs.seller_name, []):
            if candidate.ssi != ssi and last_obs.observed_at < candidate.observed_at <= confirm_after:
                relisted_obs = candidate
                break

        if relisted_obs is None:
            sold_qty = last_obs.quantity
            method = "sellout_no_relist"
            relisted_ssi = None
            relisted_qty = None
        else:
            sold_qty = max(0, last_obs.quantity - relisted_obs.quantity)
            method = "sellout_partial_relist"
            relisted_ssi = relisted_obs.ssi
            relisted_qty = relisted_obs.quantity

        if sold_qty > 0:
            events.append(
                InferredSaleEvent(
                    ssi=ssi,
                    seller_name=last_obs.seller_name,
                    map_name=last_obs.map_name,
                    quantity_sold=sold_qty,
                    sale_attributed_at=last_obs.observed_at,
                    method=method,
                    price=last_obs.price,
                    relisted_ssi=relisted_ssi,
                    relisted_quantity=relisted_qty,
                )
            )

    return events


