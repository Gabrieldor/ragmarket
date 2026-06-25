"""Shared sales-inference logic, used by both the API (for live computation/back-compat)
and the collector (which persists confirmed events -- see db.repository.record_sale_events
and CHECKLIST.md for why: a live-only computation gives no audit trail to later validate
this metric against real data).

Two distinct inference methods live here:
  - compute_sale_events: global market sales, inferred from any seller's listings.
  - compute_my_listing_sessions: the user's own sales specifically, tracked per-listing
    against the known in-game vending duration rather than the open-ended relist-grace-window
    logic used for third-party sellers (see db.repository.sync_my_listing_sessions).
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
                    relisted_ssi=relisted_ssi,
                    relisted_quantity=relisted_qty,
                )
            )

    return events


@dataclass
class MySessionResult:
    """One listing's tracked lifetime under a registered vendor alias."""

    ssi: str
    seller_name: str
    shop_name: str | None
    map_name: str | None
    price: int
    window_start: datetime
    window_end: datetime
    initial_quantity: int
    last_known_quantity: int
    total_quantity_sold: int
    status: str  # 'active' | 'expired' | 'sold_out_early'
    sale_chunks: list[tuple[datetime, int]]  # (occurred_at, quantity_sold) -- new chunks only


def compute_my_listing_sessions(
    my_observations: list, all_item_observations: list, window_hours: float | None = None
) -> list[MySessionResult]:
    """Tracks each of the user's own listings (matched by ``ssi``) for a fixed window from
    when it was first seen, instead of the open-ended relist-correction logic used for
    third-party sellers in ``compute_sale_events`` -- the window length is known (the
    in-game vending duration), so disappearance can be judged against that fixed deadline
    rather than waiting to see if a relist shows up.

    - Quantity decreases observed while still listed: confirmed sold, attributed to the
      timestamp the decrease was observed.
    - Disappears with time left in the window (we scraped the item again before window_end
      and this listing wasn't there): the remainder counts as sold too -- most likely a
      full sellout -- attributed to the last-seen timestamp.
    - Window reaches ``window_end`` with the listing still up, or not enough later scrapes
      exist yet to tell: remainder is NOT counted (still active, or expired without being
      provably sold) -- the stall closing on schedule is expected regardless of sales.

    ``my_observations`` must already be filtered to the registered vendor aliases.
    ``all_item_observations`` is the *full* observation set for the same tracked item (any
    seller), used only to know which scrape cycles actually happened, so an absence can be
    distinguished from "we just haven't scraped again yet".
    """
    if window_hours is None:
        window_hours = settings.my_listing_window_hours

    if not all_item_observations:
        return []
    cycle_times = sorted({o.observed_at for o in all_item_observations})

    by_ssi: dict[str, list] = defaultdict(list)
    for obs in my_observations:
        if obs.ssi:
            by_ssi[obs.ssi].append(obs)
    for obs_list in by_ssi.values():
        obs_list.sort(key=lambda o: o.observed_at)

    results: list[MySessionResult] = []
    window_delta = timedelta(hours=window_hours)

    for ssi, obs_list in by_ssi.items():
        first = obs_list[0]
        window_start = first.observed_at
        window_end = window_start + window_delta

        window_obs = [o for o in obs_list if o.observed_at <= window_end]

        sale_chunks: list[tuple[datetime, int]] = []
        sold = 0
        last_qty = first.quantity
        last_seen_at = window_start
        for o in window_obs[1:]:
            if o.quantity < last_qty:
                chunk = last_qty - o.quantity
                sold += chunk
                sale_chunks.append((o.observed_at, chunk))
            last_qty = o.quantity
            last_seen_at = o.observed_at

        cycles_after_last_seen_within_window = [
            t for t in cycle_times if last_seen_at < t <= window_end
        ]
        window_time_has_passed = window_end <= cycle_times[-1]

        if cycles_after_last_seen_within_window:
            # The item was scraped again within the window after we last saw this listing,
            # and it wasn't there -- conclusively disappeared early, no need to wait for the
            # rest of the window to elapse. Count the remainder as sold.
            if last_qty > 0:
                sold += last_qty
                # last_seen_at can coincide with the timestamp of the final decrease chunk
                # just recorded above (when the listing's last-seen quantity was itself the
                # result of a decrease) -- merge into that chunk instead of adding a second
                # one at the same instant, which would violate one-event-per-timestamp.
                if sale_chunks and sale_chunks[-1][0] == last_seen_at:
                    prev_at, prev_qty = sale_chunks[-1]
                    sale_chunks[-1] = (prev_at, prev_qty + last_qty)
                else:
                    sale_chunks.append((last_seen_at, last_qty))
            status = "sold_out_early"
        elif not window_time_has_passed:
            status = "active"
        else:
            status = "expired"

        results.append(
            MySessionResult(
                ssi=ssi,
                seller_name=first.seller_name,
                shop_name=first.shop_name,
                map_name=first.map_name,
                price=first.price,
                window_start=window_start,
                window_end=window_end,
                initial_quantity=first.quantity,
                last_known_quantity=last_qty,
                total_quantity_sold=sold,
                status=status,
                sale_chunks=sale_chunks,
            )
        )

    return results
