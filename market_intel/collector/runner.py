"""Collector entry point — scheduler-based, one item at a time.

Architecture:
  Items are held in a min-heap ordered by next-scrape time.  On startup they are
  staggered evenly across the target interval so there is no burst on the first
  pass.  After each successful scrape the item is rescheduled at
  (now + interval + jitter).  This spreads site traffic smoothly and is the
  primary defence against HTTP 429s.

Rate-limit avoidance (layered):
  - Even spacing:   N items × 30 min interval → one request every 1800/N seconds.
  - ±15 % jitter:  prevents robotic, clock-aligned request patterns.
  - No burst:       items are never batched; the heap naturally separates them.
  - On 429:         delay_all() pushes every queued item forward by the escalating
                    backoff, so the entire queue rests until the site recovers.
  - Escalation:     3×, 9×, 27× … capped at 4 h — a flat multiplier is not
                    enough if the site's block outlasts a single interval.

Crash resilience:
  - Observations committed per item immediately (not batched for many items).
  - Backoff escalation level reconstructed from ScrapeRun history on restart.
  - Stale "running" runs marked "interrupted" on startup.
"""

import asyncio
import heapq
import logging
import random
import signal
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from db.models import (  # noqa: E402
    CollectorStatus as CollectorStatusModel,
    ListingObservation,
    NotificationSettings,
    ScrapeRun,
    ShopLocation,
)
from db.repository import (  # noqa: E402
    finish_scrape_run,
    get_cached_shop_location,
    get_collector_config,
    get_collector_status,
    get_notification_settings,
    get_scraper_config,
    infer_and_persist_sales,
    infer_and_persist_sold_out,
    insert_observations,
    list_tracked_items,
    set_collector_status,
    start_scrape_run,
    sync_my_listing_sessions,
    upsert_shop_location,
)
from collector.rollup_jobs import run_rollup_for_date  # noqa: E402
from db.session import get_session  # noqa: E402
from notifications.checker import check_watch_rules  # noqa: E402
from notifications.discord_notifier import DiscordNotifier  # noqa: E402
from notifications.sound_notifier import SoundNotifier  # noqa: E402
from playwright_provider import RateLimitError  # noqa: E402
from scraper_adapter.provider_adapter import DetailedListing, DetailedListingProvider  # noqa: E402
from settings import settings  # noqa: E402

logger = logging.getLogger(__name__)

# Rate-limit backoff: multiplies by 3 on each consecutive 429 (3×, 9×, 27× …).
RATE_LIMIT_BACKOFF_MULTIPLIER = 3
MAX_RATE_LIMIT_BACKOFF_SECONDS = 4 * 3600

# How often to poll retry_requested while sleeping through a backoff.
_RETRY_POLL_INTERVAL = 3.0

# Random variation added to each reschedule: ±JITTER_PCT × interval.
_JITTER_PCT = 0.15

# Re-sync item list from DB this often (picks up newly added / deactivated items).
_SYNC_INTERVAL = 300.0

# Run watch-rules check at most this often during idle windows.
_WATCH_RULES_INTERVAL = 300.0

# Reschedule a failed item (non-429 error) this many seconds from now.
_ITEM_RETRY_DELAY = 60.0


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@dataclass(order=True)
class _ScheduledItem:
    """A single tracked item with its next-scrape timestamp.

    Ordering by (next_at, item_id) makes this directly usable in a min-heap.
    All other fields carry metadata needed by the scraper.
    """
    next_at: float            # monotonic timestamp; heap key
    item_id: int              # tiebreaker
    item_name: str            = field(compare=False)
    server_name: str          = field(compare=False)
    store_type: str           = field(compare=False)
    sold_out_enabled: bool    = field(compare=False)
    interval_seconds: int     = field(compare=False)


class ItemScheduler:
    """Min-heap of scheduled items.  Single-threaded (asyncio); no locking needed."""

    def __init__(self) -> None:
        self._heap: list[_ScheduledItem] = []

    # ------------------------------------------------------------------ load

    def load(self, items: list, default_interval: int) -> None:
        """Initial load: stagger items evenly across one full interval."""
        n = len(items)
        now = time.monotonic()
        for i, item in enumerate(items):
            interval = item.poll_interval_override or default_interval
            # Spread offsets: item 0 at ~0 s, item N-1 at ~interval s.
            offset = (i / n) * interval if n > 0 else 0
            # Small startup jitter so items don't align on the second.
            offset += random.uniform(-0.05, 0.05) * interval
            self._push_raw(item, interval, next_at=now + max(0.0, offset))
        logger.info(
            "Scheduler: %d item(s) loaded, spread over %d s (~%.1f min).",
            n, default_interval, default_interval / 60,
        )

    # ------------------------------------------------------------------ sync

    def sync(self, active_items: list, default_interval: int) -> None:
        """Add new items; remove deactivated ones; refresh intervals on existing ones.

        Called every _SYNC_INTERVAL seconds so that changes to poll_interval_seconds
        (or a per-item poll_interval_override) take effect without a restart.
        """
        current_ids = {s.item_id for s in self._heap}
        active_map = {item.id: item for item in active_items}

        removed = current_ids - active_map.keys()
        if removed:
            self._heap = [s for s in self._heap if s.item_id not in removed]
            heapq.heapify(self._heap)
            logger.info("Scheduler: removed %d deactivated item(s).", len(removed))

        for scheduled in self._heap:
            item = active_map.get(scheduled.item_id)
            if item is None:
                continue
            new_interval = item.poll_interval_override or default_interval
            if new_interval != scheduled.interval_seconds:
                logger.info(
                    "Scheduler: '%s' interval updated %d s → %d s.",
                    scheduled.item_name, scheduled.interval_seconds, new_interval,
                )
                scheduled.interval_seconds = new_interval

        for item_id, item in active_map.items():
            if item_id not in current_ids:
                interval = item.poll_interval_override or default_interval
                # Schedule at a random point in the next interval to avoid a herd.
                next_at = time.monotonic() + random.uniform(0, interval)
                self._push_raw(item, interval, next_at=next_at)
                logger.info(
                    "Scheduler: new item '%s' queued in ~%.0f s.",
                    item.item_name, next_at - time.monotonic(),
                )

    # ------------------------------------------------------------------ core ops

    def peek(self) -> _ScheduledItem | None:
        return self._heap[0] if self._heap else None

    def pop(self) -> _ScheduledItem:
        return heapq.heappop(self._heap)

    def reschedule(self, item: _ScheduledItem) -> None:
        """Re-queue item after a successful scrape: interval ± jitter."""
        jitter = random.uniform(-_JITTER_PCT, _JITTER_PCT) * item.interval_seconds
        item.next_at = time.monotonic() + item.interval_seconds + jitter
        heapq.heappush(self._heap, item)
        logger.debug(
            "[%s] rescheduled in %.0f s.", item.item_name,
            item.next_at - time.monotonic(),
        )

    def reschedule_soon(self, item: _ScheduledItem, delay: float) -> None:
        """Re-queue item with a specific delay (used for retries and post-backoff)."""
        item.next_at = time.monotonic() + delay
        heapq.heappush(self._heap, item)

    def delay_all(self, seconds: float) -> None:
        """Push every item's next-scrape time forward by `seconds`.

        Used on rate-limit: the whole queue rests, not just the failing item.
        """
        for s in self._heap:
            s.next_at += seconds
        heapq.heapify(self._heap)
        logger.info(
            "Scheduler: all %d item(s) pushed forward by %.0f s (%.1f min).",
            len(self._heap), seconds, seconds / 60,
        )

    def is_empty(self) -> bool:
        return not self._heap

    # ------------------------------------------------------------------ internal

    def _push_raw(self, item, interval: int, *, next_at: float) -> None:
        heapq.heappush(self._heap, _ScheduledItem(
            next_at=next_at,
            item_id=item.id,
            item_name=item.item_name,
            server_name=item.server_name,
            store_type=item.store_type,
            sold_out_enabled=item.sold_out_enabled,
            interval_seconds=interval,
        ))


# ---------------------------------------------------------------------------
# Sleep helpers
# ---------------------------------------------------------------------------

async def _interruptible_sleep(seconds: float, stop_event: asyncio.Event) -> bool:
    """Sleep for up to `seconds`, waking early on stop or retry_requested.

    Returns True if a retry was requested (caller should reset
    consecutive_rate_limits), False if the full duration elapsed or stop fired.
    """
    deadline = time.monotonic() + seconds
    while not stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        await asyncio.sleep(min(_RETRY_POLL_INTERVAL, remaining))
        with get_session() as session:
            status = get_collector_status(session)
            if status and status.retry_requested:
                status.retry_requested = False
                session.commit()
                logger.info("Retry requested — abandoning backoff sleep.")
                return True
    return False


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

async def _scrape_one_item(
    provider: DetailedListingProvider,
    item: _ScheduledItem,
    run_id: int,
    location_click_delay_seconds: float,
) -> tuple[int, int]:
    """Scrape one item, resolve locations, flag outliers, and commit.

    Returns (observation_count, fresh_location_lookup_count).
    """
    cycle_cache: dict[tuple[str, str], ShopLocation] = {}
    lookup_requested: set[tuple[str, str]] = set()
    location_lookups = 0

    # Timestamp set before the network call so all observations from this
    # scrape share the same observed_at (representing when the snapshot started).
    observed_at = datetime.now()

    with get_session() as session:

        def needs_location(listing: DetailedListing) -> bool:
            key = (listing.seller_name or "", listing.shop_name or "")
            if key in cycle_cache or key in lookup_requested:
                return False
            cached = get_cached_shop_location(
                session,
                seller_name=key[0],
                shop_name=key[1],
                server_name=item.server_name,
            )
            if cached:
                cycle_cache[key] = cached
                return False
            lookup_requested.add(key)
            return True

        results = await provider.scrape_item(
            item.item_name,
            item.store_type,
            item.server_name,
            needs_location,
            max_pages=1,
            location_click_delay_seconds=location_click_delay_seconds,
        )

        observations: list[ListingObservation] = []
        for rank, (listing, location) in enumerate(results, start=1):
            key = (listing.seller_name or "", listing.shop_name or "")
            shop_loc: ShopLocation | None

            if location is not None:
                location_lookups += 1
                shop_loc = upsert_shop_location(
                    session,
                    seller_name=key[0],
                    shop_name=key[1],
                    server_name=item.server_name,
                    map_id=None,
                    map_name=location.map_name,
                    x_pos=location.x_pos,
                    y_pos=location.y_pos,
                )
                cycle_cache[key] = shop_loc
                source = "fresh_lookup"
            else:
                shop_loc = cycle_cache.get(key)
                source = "cache" if shop_loc else None

            observations.append(
                ListingObservation(
                    tracked_item_id=item.item_id,
                    scrape_run_id=run_id,
                    observed_at=observed_at,
                    ssi=listing.ssi,
                    item_id=listing.item_id,
                    price=listing.price,
                    quantity=listing.quantity,
                    seller_name=listing.seller_name,
                    shop_name=listing.shop_name,
                    server_name=item.server_name,
                    store_type=item.store_type,
                    map_name=shop_loc.map_name if shop_loc else None,
                    x_pos=shop_loc.x_pos if shop_loc else None,
                    y_pos=shop_loc.y_pos if shop_loc else None,
                    location_source=source,
                    page_num=1,
                    rank_on_page=rank,
                )
            )

        # Outlier flagging: price > factor × cycle median.
        if len(observations) >= 2:
            factor = get_scraper_config(session).outlier_factor
            median_price = statistics.median(o.price for o in observations)
            threshold = factor * median_price
            for obs in observations:
                obs.is_outlier = obs.price > threshold

        insert_observations(session, observations)
        infer_and_persist_sales(session, item.item_id)
        sync_my_listing_sessions(session, item.item_id)
        if item.sold_out_enabled:
            infer_and_persist_sold_out(session, item.item_id)

    return len(observations), location_lookups


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------

def _mark_interrupted_runs() -> None:
    """On startup, flag any scrape_runs left in 'running' state by a previous crash."""
    with get_session() as session:
        stale = list(session.scalars(select(ScrapeRun).where(ScrapeRun.status == "running")))
        for run in stale:
            run.status = "interrupted"
            run.finished_at = run.finished_at or datetime.now()
        if stale:
            logger.warning("Marked %d stale 'running' scrape run(s) as 'interrupted'.", len(stale))


def _count_recent_consecutive_rate_limits() -> int:
    """Reconstruct the backoff escalation counter from ScrapeRun history.

    The counter lives in memory, so a process restart would forget how many
    consecutive 429s already happened.  Reading from history prevents retrying
    too soon after a restart during an active block.
    """
    with get_session() as session:
        recent = list(
            session.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(20))
        )
    count = 0
    for run in recent:
        if run.status == "rate_limited":
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# Notifier helpers
# ---------------------------------------------------------------------------

def _notifier_signature(config: NotificationSettings) -> tuple:
    return (config.local_sound, config.discord_token, config.channel_id, config.user_mention)


def _build_notifier(config: NotificationSettings):
    if config.local_sound:
        return SoundNotifier(user_mention=config.user_mention)
    return DiscordNotifier(
        token=config.discord_token or "",
        channel_id=int(config.channel_id) if config.channel_id else 0,
        user_mention=config.user_mention,
    )


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    _mark_interrupted_runs()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown(sig_name: str) -> None:
        logger.info("Shutdown signal (%s) — stopping after current item.", sig_name)
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _shutdown, "SIGINT")
        loop.add_signal_handler(signal.SIGTERM, _shutdown, "SIGTERM")
    except (NotImplementedError, AttributeError):
        pass  # Windows: Ctrl-C raises KeyboardInterrupt instead

    # ── Startup rate-limit backoff ────────────────────────────────────────────
    # Reconstruct escalation level from history so a restart doesn't forget.
    consecutive_rate_limits = _count_recent_consecutive_rate_limits()
    if consecutive_rate_limits > 0:
        with get_session() as session:
            _cfg = get_collector_config(session)
        resume_wait = min(
            _cfg.poll_interval_seconds * (RATE_LIMIT_BACKOFF_MULTIPLIER ** consecutive_rate_limits),
            MAX_RATE_LIMIT_BACKOFF_SECONDS,
        )
        logger.warning(
            "Resuming after %d consecutive rate-limited run(s); "
            "waiting %.1f s (%.1f min) before first scrape.",
            consecutive_rate_limits, resume_wait, resume_wait / 60,
        )
        with get_session() as session:
            set_collector_status(
                session,
                state="rate_limited",
                next_cycle_at=datetime.now() + timedelta(seconds=resume_wait),
                consecutive_rate_limits=consecutive_rate_limits,
            )
        await _interruptible_sleep(resume_wait, stop_event)
        consecutive_rate_limits = 0

    # ── Browser ───────────────────────────────────────────────────────────────
    async def new_provider() -> DetailedListingProvider:
        p = DetailedListingProvider(
            headless=settings.headless,
            timeout=settings.browser_timeout_ms,
            page_delay=3.0,
        )
        await p.setup()
        return p

    provider = await new_provider()

    # ── Notifier ──────────────────────────────────────────────────────────────
    with get_session() as session:
        notif_config = get_notification_settings(session)
    notifier = _build_notifier(notif_config)
    await notifier.start()
    notifier_signature = _notifier_signature(notif_config)

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler = ItemScheduler()
    with get_session() as session:
        initial_items = list_tracked_items(session, active_only=True)
        cfg = get_collector_config(session)
    scheduler.load(initial_items, cfg.poll_interval_seconds)

    last_sync_at = time.monotonic()
    last_watch_rules_at = 0.0      # run immediately on first idle window
    last_rollup_date: date | None = None

    try:
        while not stop_event.is_set():

            # ── Pause gate ────────────────────────────────────────────────
            with get_session() as session:
                status_row = get_collector_status(session)
                is_paused = status_row.paused if status_row else False
            if is_paused:
                with get_session() as session:
                    set_collector_status(session, state="paused")
                logger.info("Collector paused — waiting for resume.")
                while not stop_event.is_set():
                    await asyncio.sleep(3)
                    with get_session() as session:
                        status_row = get_collector_status(session)
                        if not (status_row and status_row.paused):
                            break
                logger.info("Collector resumed.")
                with get_session() as session:
                    set_collector_status(session, state="starting")
                if stop_event.is_set():
                    break

            # ── Browser health ────────────────────────────────────────────
            if not provider._browser.is_connected():
                logger.warning("Browser disconnected — relaunching.")
                try:
                    await provider.teardown()
                except Exception:
                    pass
                try:
                    provider = await new_provider()
                except Exception:
                    logger.exception("Browser relaunch failed — retrying in 60 s.")
                    await asyncio.sleep(60)
                    continue

            # ── Notifier hot-reload ───────────────────────────────────────
            with get_session() as session:
                notif_config = get_notification_settings(session)
            new_sig = _notifier_signature(notif_config)
            if new_sig != notifier_signature:
                logger.info("Notification settings changed — rebuilding notifier.")
                await notifier.close()
                notifier = _build_notifier(notif_config)
                await notifier.start()
                notifier_signature = new_sig

            # ── Periodic item-list sync ───────────────────────────────────
            now_mono = time.monotonic()
            if now_mono - last_sync_at >= _SYNC_INTERVAL:
                with get_session() as session:
                    fresh_items = list_tracked_items(session, active_only=True)
                    cfg = get_collector_config(session)
                scheduler.sync(fresh_items, cfg.poll_interval_seconds)
                last_sync_at = time.monotonic()

            # ── Nothing to do ─────────────────────────────────────────────
            if scheduler.is_empty():
                logger.info("No active items — sleeping 30 s.")
                with get_session() as session:
                    set_collector_status(session, state="sleeping")
                await asyncio.sleep(30)
                continue

            # ── Wait for next item ────────────────────────────────────────
            next_item = scheduler.peek()
            wait = next_item.next_at - time.monotonic()

            if wait > 0:
                # Use idle time for watch-rules if they're due.
                if time.monotonic() - last_watch_rules_at >= _WATCH_RULES_INTERVAL:
                    try:
                        with get_session() as session:
                            _notif_cfg = get_notification_settings(session)
                            await check_watch_rules(session, provider, notifier, _notif_cfg)
                        last_watch_rules_at = time.monotonic()
                    except RateLimitError:
                        # Don't escalate the item-scraping backoff for a watch-rules 429;
                        # just skip this pass and try again next idle window.
                        logger.warning("Rate limited during watch-rules check — skipping pass.")
                        last_watch_rules_at = time.monotonic()
                    except Exception:
                        logger.exception("Unhandled error in watch-rules check.")

                # Recompute wait after any time spent on watch rules.
                wait = next_item.next_at - time.monotonic()
                if wait > 0:
                    with get_session() as session:
                        set_collector_status(
                            session,
                            state="sleeping",
                            next_cycle_at=datetime.now() + timedelta(seconds=wait),
                        )
                    await asyncio.sleep(min(wait, _RETRY_POLL_INTERVAL))
                continue

            # ── Scrape ───────────────────────────────────────────────────
            scheduled = scheduler.pop()

            with get_session() as session:
                cfg = get_collector_config(session)
                run = start_scrape_run(session)
                run_id = run.id

            with get_session() as session:
                set_collector_status(
                    session, state="scraping", current_item_name=scheduled.item_name,
                )

            scrape_start = time.monotonic()
            try:
                obs_count, lookups = await _scrape_one_item(
                    provider, scheduled, run_id,
                    location_click_delay_seconds=cfg.location_click_delay_seconds,
                )

            except RateLimitError:
                elapsed = time.monotonic() - scrape_start
                logger.warning(
                    "Rate limited (HTTP 429) scraping '%s' after %.1f s.",
                    scheduled.item_name, elapsed,
                )
                with get_session() as session:
                    run = session.get(ScrapeRun, run_id)
                    finish_scrape_run(
                        session, run,
                        items_attempted=1, items_succeeded=0,
                        location_lookups_performed=0,
                        status="rate_limited",
                    )

                consecutive_rate_limits += 1
                backoff = min(
                    cfg.poll_interval_seconds
                    * (RATE_LIMIT_BACKOFF_MULTIPLIER ** consecutive_rate_limits),
                    MAX_RATE_LIMIT_BACKOFF_SECONDS,
                )
                logger.warning(
                    "Consecutive 429s: %d — pushing all items forward %.0f s (%.1f min).",
                    consecutive_rate_limits, backoff, backoff / 60,
                )

                # Push every queued item forward, then re-queue the popped one.
                scheduler.delay_all(backoff)
                scheduler.reschedule_soon(scheduled, backoff)

                with get_session() as session:
                    set_collector_status(
                        session,
                        state="rate_limited",
                        next_cycle_at=datetime.now() + timedelta(seconds=backoff),
                        consecutive_rate_limits=consecutive_rate_limits,
                    )

                retry = await _interruptible_sleep(backoff, stop_event)
                if retry:
                    consecutive_rate_limits = 0
                continue

            except Exception:
                elapsed = time.monotonic() - scrape_start
                logger.exception(
                    "[%s] scrape failed after %.1f s — retrying in %.0f s.",
                    scheduled.item_name, elapsed, _ITEM_RETRY_DELAY,
                )
                with get_session() as session:
                    run = session.get(ScrapeRun, run_id)
                    finish_scrape_run(
                        session, run,
                        items_attempted=1, items_succeeded=0,
                        location_lookups_performed=0,
                        status="interrupted",
                    )
                scheduler.reschedule_soon(scheduled, _ITEM_RETRY_DELAY)
                continue

            # ── Success ───────────────────────────────────────────────────
            elapsed = time.monotonic() - scrape_start
            consecutive_rate_limits = 0

            with get_session() as session:
                run = session.get(ScrapeRun, run_id)
                finish_scrape_run(
                    session, run,
                    items_attempted=1, items_succeeded=1,
                    location_lookups_performed=lookups,
                    status="success",
                )

            scheduler.reschedule(scheduled)
            next_in = scheduled.next_at - time.monotonic()
            logger.info(
                "[%s] %.1f s — %d listing(s), %d fresh location(s). "
                "Next scrape in ~%.0f s (~%.1f min).",
                scheduled.item_name, elapsed, obs_count, lookups,
                next_in, next_in / 60,
            )

            # Nightly rollup: run once per calendar day on the first successful scrape.
            today = datetime.now().date()
            if last_rollup_date != today:
                with get_session() as session:
                    try:
                        run_rollup_for_date(session, today)
                        session.commit()
                        last_rollup_date = today
                        logger.info("Rollup complete for %s.", today)
                    except Exception:
                        logger.exception("Rollup failed — stats may be stale until next run.")

            # Inter-item delay: pause before the next scrape to avoid back-to-back
            # requests hammering the site when multiple items are due simultaneously.
            if cfg.item_delay_seconds > 0:
                logger.debug("Inter-item delay: sleeping %.1f s.", cfg.item_delay_seconds)
                await asyncio.sleep(cfg.item_delay_seconds)

    except KeyboardInterrupt:
        logger.info("Collector stopped (KeyboardInterrupt).")
    finally:
        await provider.teardown()
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(main())
