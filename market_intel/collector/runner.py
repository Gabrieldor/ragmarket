"""Collector entry point: each cycle checks watch rules (the ported price watcher, see
notifications/) first, then scrapes all active tracked items and persists observations,
runs indefinitely.

Cadence: targets a fixed poll interval. Time spent on cache-miss location lookups and
watch-rule checks during a cycle is subtracted from the sleep before the next cycle
(ARCHITECTURE.md section 2), so the loop stays anchored to roughly poll_interval_seconds
regardless of how much of that time went to watch rules vs. tracked items.

Crash resilience: each tracked item's observations are committed to the database
as soon as that item finishes scraping (not batched for the whole cycle), so a
crash partway through a cycle only loses the in-progress item, not everything
scraped so far that cycle.
"""

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from db.models import ListingObservation, NotificationSettings, ScrapeRun, ShopLocation  # noqa: E402
from db.repository import (  # noqa: E402
    finish_scrape_run,
    get_cached_shop_location,
    get_notification_settings,
    infer_and_persist_sales,
    infer_and_persist_sold_out,
    insert_observations,
    list_tracked_items,
    set_collector_status,
    start_scrape_run,
    sync_my_listing_sessions,
    upsert_shop_location,
)
from db.session import get_session  # noqa: E402
from notifications.checker import check_watch_rules  # noqa: E402
from notifications.discord_notifier import DiscordNotifier  # noqa: E402
from notifications.sound_notifier import SoundNotifier  # noqa: E402
from playwright_provider import RateLimitError  # noqa: E402
from scraper_adapter.provider_adapter import DetailedListing, DetailedListingProvider  # noqa: E402
from settings import settings  # noqa: E402

logger = logging.getLogger(__name__)

RATE_LIMIT_BACKOFF_MULTIPLIER = 3  # base backoff multiplier on the first consecutive 429
MAX_RATE_LIMIT_BACKOFF_SECONDS = 4 * 3600  # cap: don't wait longer than this between retries


async def _scrape_one_item(
    provider: DetailedListingProvider,
    tracked_item_id: int,
    item_name: str,
    server_name: str,
    store_type: str,
    observed_at: datetime,
    run_id: int,
    sold_out_enabled: bool,
) -> tuple[int, int]:
    """Scrape one tracked item, resolve locations (cache or fresh lookup), and commit
    its observations immediately. Returns (observation count, fresh location lookup count).
    """
    cycle_cache: dict[tuple[str, str], ShopLocation] = {}
    location_lookups = 0

    with get_session() as session:

        def needs_location(listing: DetailedListing) -> bool:
            key = (listing.seller_name or "", listing.shop_name or "")
            if key in cycle_cache:
                return False
            cached = get_cached_shop_location(
                session, seller_name=key[0], shop_name=key[1], server_name=server_name
            )
            if cached:
                cycle_cache[key] = cached
                return False
            return True

        results = await provider.scrape_item(
            item_name, store_type, server_name, needs_location, max_pages=1
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
                    server_name=server_name,
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
                    tracked_item_id=tracked_item_id,
                    scrape_run_id=run_id,
                    observed_at=observed_at,
                    ssi=listing.ssi,
                    item_id=listing.item_id,
                    price=listing.price,
                    quantity=listing.quantity,
                    seller_name=listing.seller_name,
                    shop_name=listing.shop_name,
                    server_name=server_name,
                    store_type=store_type,
                    map_name=shop_loc.map_name if shop_loc else None,
                    x_pos=shop_loc.x_pos if shop_loc else None,
                    y_pos=shop_loc.y_pos if shop_loc else None,
                    location_source=source,
                    page_num=1,
                    rank_on_page=rank,
                )
            )

        insert_observations(session, observations)
        # Confirms and persists any sale events that have cleared their grace window since
        # the last cycle -- run here (right after fresh data for this item lands) rather
        # than as a separate scheduled job, so confirmations happen as soon as possible.
        infer_and_persist_sales(session, tracked_item_id)
        # Updates "my sales" listing sessions the same way, if any vendor aliases are
        # registered (no-op otherwise).
        sync_my_listing_sessions(session, tracked_item_id)
        # Low-stock detection, per the item's own opt-in/out toggle.
        if sold_out_enabled:
            infer_and_persist_sold_out(session, tracked_item_id)

    return len(observations), location_lookups


async def run_cycle(provider: DetailedListingProvider) -> bool:
    """Runs one scrape cycle. Returns True if rate-limited (caller should back off harder)."""
    with get_session() as session:
        tracked = [
            (item.id, item.item_name, item.server_name, item.store_type, item.sold_out_enabled)
            for item in list_tracked_items(session, active_only=True)
        ]
        run = start_scrape_run(session)
        run_id = run.id

    if not tracked:
        logger.info("No active tracked items. Nothing to scrape this cycle.")
        with get_session() as session:
            run = session.get(ScrapeRun, run_id)
            finish_scrape_run(
                session, run, items_attempted=0, items_succeeded=0, location_lookups_performed=0
            )
        return False

    items_attempted = 0
    items_succeeded = 0
    observations_total = 0
    location_lookups_total = 0
    rate_limited = False

    for index, (tracked_item_id, item_name, server_name, store_type, sold_out_enabled) in enumerate(tracked):
        if index > 0:
            await asyncio.sleep(settings.item_delay_seconds)

        with get_session() as session:
            set_collector_status(session, state="scraping", current_item_name=item_name)

        items_attempted += 1
        observed_at = datetime.now()
        try:
            obs_count, lookups = await _scrape_one_item(
                provider, tracked_item_id, item_name, server_name, store_type, observed_at,
                run_id, sold_out_enabled,
            )
        except RateLimitError:
            logger.warning(
                "Rate limited (HTTP 429) while scraping '%s' -- stopping this cycle early "
                "and backing off before the next one.",
                item_name,
            )
            rate_limited = True
            break
        except Exception:
            logger.exception("Failed to scrape '%s'", item_name)
            continue

        observations_total += obs_count
        location_lookups_total += lookups
        items_succeeded += 1
        logger.info(
            "[%s] %d listing(s), %d fresh location lookup(s)", item_name, obs_count, lookups
        )

    with get_session() as session:
        run = session.get(ScrapeRun, run_id)
        finish_scrape_run(
            session,
            run,
            items_attempted=items_attempted,
            items_succeeded=items_succeeded,
            location_lookups_performed=location_lookups_total,
            status="rate_limited" if rate_limited else "success",
        )

    logger.info(
        "Cycle complete: %d/%d item(s) succeeded, %d observation(s) written, %d fresh location "
        "lookup(s)%s.",
        items_succeeded, items_attempted, observations_total, location_lookups_total,
        " (stopped early: rate limited)" if rate_limited else "",
    )
    return rate_limited


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
    """The backoff escalation counter only lives in memory, so a process restart would
    otherwise forget how many consecutive 429s already happened and retry too soon --
    reconstruct it from scrape_runs history instead.
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


def _notifier_signature(config: NotificationSettings) -> tuple:
    """Fields that determine which concrete notifier to build and how to configure it --
    used to detect a settings change between cycles and rebuild the notifier without a
    process restart.
    """
    return (config.local_sound, config.discord_token, config.channel_id, config.user_mention)


def _build_notifier(config: NotificationSettings):
    if config.local_sound:
        return SoundNotifier(user_mention=config.user_mention)
    return DiscordNotifier(
        token=config.discord_token or "",
        channel_id=int(config.channel_id) if config.channel_id else 0,
        user_mention=config.user_mention,
    )


async def main() -> None:
    # Without this, Windows defaults stdout/stderr to the console codepage (cp1252 here),
    # which silently mangles non-ASCII item/seller/shop names (e.g. accented Portuguese
    # item names) whenever output is redirected to a log file.
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
        logger.info("Shutdown signal received (%s)", sig_name)
        stop_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _shutdown, "SIGINT")
        loop.add_signal_handler(signal.SIGTERM, _shutdown, "SIGTERM")
    except (NotImplementedError, AttributeError):
        pass  # Windows: Ctrl-C raises KeyboardInterrupt below instead

    # Resuming after a crash/restart shouldn't forget how many consecutive 429s already
    # happened -- reconstruct the escalation level from scrape_runs history and, if nonzero,
    # wait out the appropriate backoff *before* even launching the browser, rather than
    # retrying immediately and risking extending an still-active block.
    consecutive_rate_limits = _count_recent_consecutive_rate_limits()
    if consecutive_rate_limits > 0:
        resume_wait = min(
            settings.poll_interval_seconds * (RATE_LIMIT_BACKOFF_MULTIPLIER**consecutive_rate_limits),
            MAX_RATE_LIMIT_BACKOFF_SECONDS,
        )
        logger.warning(
            "Resuming after %d consecutive rate-limited run(s) in history; waiting %.1fs "
            "before the first cycle instead of retrying immediately.",
            consecutive_rate_limits, resume_wait,
        )
        with get_session() as session:
            set_collector_status(
                session,
                state="rate_limited",
                next_cycle_at=datetime.now() + timedelta(seconds=resume_wait),
                consecutive_rate_limits=consecutive_rate_limits,
            )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=resume_wait)
        except asyncio.TimeoutError:
            pass

    async def new_provider() -> DetailedListingProvider:
        p = DetailedListingProvider(
            headless=settings.headless,
            timeout=settings.browser_timeout_ms,
            page_delay=3.0,
        )
        await p.setup()
        return p

    provider = await new_provider()

    with get_session() as session:
        notif_config = get_notification_settings(session)
    notifier = _build_notifier(notif_config)
    await notifier.start()
    notifier_signature = _notifier_signature(notif_config)

    try:
        while not stop_event.is_set():
            # The browser process can die out-of-band (OOM, an external kill, a crash) without
            # the collector's own process dying -- since the browser instance is reused across
            # cycles for efficiency, an undetected death would otherwise fail every single
            # future cycle forever. Check before each cycle and relaunch if needed.
            if not provider._browser.is_connected():
                logger.warning("Browser is disconnected -- relaunching before this cycle.")
                try:
                    await provider.teardown()
                except Exception:
                    pass
                provider = await new_provider()

            with get_session() as session:
                notif_config = get_notification_settings(session)
            new_signature = _notifier_signature(notif_config)
            if new_signature != notifier_signature:
                logger.info("Notification settings changed -- rebuilding notifier.")
                await notifier.close()
                notifier = _build_notifier(notif_config)
                await notifier.start()
                notifier_signature = new_signature

            cycle_start = time.monotonic()
            rate_limited = False
            # Watch rules check first (the ported price watcher), then the tracked-item
            # scrape -- both share this one cycle's elapsed-time budget (sleep_for below).
            try:
                with get_session() as session:
                    await check_watch_rules(session, provider, notifier, notif_config)
            except RateLimitError:
                logger.warning(
                    "Rate limited (HTTP 429) while checking watch rules -- skipping the "
                    "tracked-item scrape this cycle."
                )
                rate_limited = True
            except Exception:
                logger.exception("Unhandled error while checking watch rules")

            if not rate_limited:
                try:
                    rate_limited = await run_cycle(provider)
                except Exception:
                    logger.exception("Unhandled error during scrape cycle")

            elapsed = time.monotonic() - cycle_start
            target_interval = settings.poll_interval_seconds
            if rate_limited:
                # Escalates with each consecutive 429 (3x, 9x, 27x, ... capped) rather than a
                # flat multiplier -- a single fixed backoff isn't enough if the site's block
                # outlasts it, and retrying at a fixed short interval against a still-active
                # block risks extending it further.
                consecutive_rate_limits += 1
                backoff_factor = RATE_LIMIT_BACKOFF_MULTIPLIER**consecutive_rate_limits
                target_interval = min(
                    target_interval * backoff_factor, MAX_RATE_LIMIT_BACKOFF_SECONDS
                )
            else:
                consecutive_rate_limits = 0
            sleep_for = max(0.0, target_interval - elapsed)
            logger.info(
                "Cycle took %.1fs; sleeping %.1fs before next cycle (target interval %ds%s).",
                elapsed, sleep_for, target_interval,
                f" -- rate-limit backoff, consecutive hits: {consecutive_rate_limits}"
                if rate_limited else "",
            )
            with get_session() as session:
                set_collector_status(
                    session,
                    state="rate_limited" if rate_limited else "sleeping",
                    next_cycle_at=datetime.now() + timedelta(seconds=sleep_for),
                    consecutive_rate_limits=consecutive_rate_limits,
                )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                pass
    except KeyboardInterrupt:
        logger.info("Collector stopped (KeyboardInterrupt).")
    finally:
        await provider.teardown()
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(main())
