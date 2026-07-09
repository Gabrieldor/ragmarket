"""Collector entry point — sequential, one item at a time.

Architecture:
  Each cycle fetches all active tracked items from the DB and scrapes them
  sequentially with item_delay_seconds between each one.  After all items are
  done the collector sleeps poll_interval_seconds before starting the next
  cycle.  This keeps the logic simple and predictable.

Rate-limit avoidance:
  - item_delay_seconds between consecutive scrapes.
  - location_click_delay_seconds between modal clicks within one item.
  - On 429: exponential backoff (3×, 9×, 27× … capped at 4 h), then retry
    from the beginning of a fresh cycle.

Crash resilience:
  - Observations committed per item immediately.
  - Backoff escalation level reconstructed from ScrapeRun history on restart.
  - Stale "running" runs marked "interrupted" on startup.
"""

import asyncio
import logging
import signal
import statistics
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx

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

RATE_LIMIT_BACKOFF_MULTIPLIER = 3
MAX_RATE_LIMIT_BACKOFF_SECONDS = 4 * 3600
_RETRY_POLL_INTERVAL = 3.0

# IP auto-rotation: a cycle is "bad" if every item attempted that cycle hit the
# location circuit breaker (see DetailedListingProvider.last_item_hit_circuit_breaker).
# After this many consecutive bad cycles, POST /admin/rotate-ip once and reset.
CONSECUTIVE_BAD_CYCLES_THRESHOLD = 1
_ROTATE_IP_URL = "http://localhost:8000/admin/rotate-ip"


# ---------------------------------------------------------------------------
# Sleep helper
# ---------------------------------------------------------------------------

async def _interruptible_sleep(seconds: float, stop_event: asyncio.Event) -> bool:
    """Sleep up to `seconds`, waking early on stop or retry_requested.

    Returns True if a retry was requested, False otherwise.
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
    item,
    run_id: int,
    location_click_delay_seconds: float,
) -> tuple[int, int, int]:
    """Scrape one item, resolve locations, flag outliers, and commit.

    Returns (observation_count, fresh_location_lookup_count, location_lookup_attempts).
    """
    cycle_cache: dict[tuple[str, str], ShopLocation] = {}
    lookup_requested: set[tuple[str, str]] = set()
    location_lookups = 0
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
        location_attempts = provider.last_item_location_attempts

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
                    tracked_item_id=item.id,
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

        if len(observations) >= 2:
            factor = get_scraper_config(session).outlier_factor
            median_price = statistics.median(o.price for o in observations)
            threshold = factor * median_price
            for obs in observations:
                obs.is_outlier = obs.price > threshold

        insert_observations(session, observations)
        infer_and_persist_sales(session, item.id)
        if item.sold_out_enabled:
            infer_and_persist_sold_out(session, item.id)

    return len(observations), location_lookups, location_attempts


# ---------------------------------------------------------------------------
# Startup helpers
# ---------------------------------------------------------------------------

def _mark_interrupted_runs() -> None:
    with get_session() as session:
        stale = list(session.scalars(select(ScrapeRun).where(ScrapeRun.status == "running")))
        for run in stale:
            run.status = "interrupted"
            run.finished_at = run.finished_at or datetime.now()
        if stale:
            logger.warning("Marked %d stale 'running' scrape run(s) as 'interrupted'.", len(stale))


def _count_recent_consecutive_rate_limits() -> int:
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
        pass

    # Reconstruct backoff level from history so a restart doesn't forget.
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

    # Browser
    async def new_provider() -> DetailedListingProvider:
        p = DetailedListingProvider(
            headless=settings.headless,
            timeout=settings.browser_timeout_ms,
            page_delay=3.0,
        )
        await p.setup()
        return p

    provider = await new_provider()

    # Notifier
    with get_session() as session:
        notif_config = get_notification_settings(session)
    notifier = _build_notifier(notif_config)
    await notifier.start()
    notifier_signature = _notifier_signature(notif_config)

    consecutive_bad_cycles = 0

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

            # ── Fetch items and config ────────────────────────────────────
            with get_session() as session:
                items = list_tracked_items(session, active_only=True)
                cfg = get_collector_config(session)

            if not items:
                logger.info("No active tracked items — sleeping 30 s.")
                with get_session() as session:
                    set_collector_status(session, state="sleeping")
                await asyncio.sleep(30)
                continue

            # ── Scrape all items sequentially ─────────────────────────────
            tracked_item_aliases: set[str] = set()
            for _it in items:
                tracked_item_aliases.add(_it.item_name.strip().lower())
                if _it.display_name:
                    tracked_item_aliases.add(_it.display_name.strip().lower())

            cycle_start = time.monotonic()
            rate_limited_this_cycle = False
            bad_items_this_cycle = 0
            items_attempted_this_cycle = 0
            total_location_attempts_this_cycle = 0
            total_location_successes_this_cycle = 0

            for i, item in enumerate(items):
                if stop_event.is_set():
                    break

                with get_session() as session:
                    run = start_scrape_run(session)
                    run_id = run.id

                with get_session() as session:
                    set_collector_status(
                        session, state="scraping", current_item_name=item.item_name,
                    )

                scrape_start = time.monotonic()
                try:
                    obs_count, lookups, attempts = await _scrape_one_item(
                        provider, item, run_id,
                        location_click_delay_seconds=cfg.location_click_delay_seconds,
                    )
                    items_attempted_this_cycle += 1
                    total_location_attempts_this_cycle += attempts
                    total_location_successes_this_cycle += lookups
                    if provider.last_item_hit_circuit_breaker:
                        bad_items_this_cycle += 1

                    with get_session() as session:
                        set_collector_status(
                            session, state="scraping", current_item_name=item.item_name,
                            location_lookup_warning=provider.last_item_hit_circuit_breaker,
                        )

                except RateLimitError:
                    elapsed = time.monotonic() - scrape_start
                    logger.warning(
                        "Rate limited (HTTP 429) scraping '%s' after %.1f s.",
                        item.item_name, elapsed,
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
                        "Consecutive 429s: %d — backing off %.0f s (%.1f min).",
                        consecutive_rate_limits, backoff, backoff / 60,
                    )
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
                    rate_limited_this_cycle = True
                    break  # stop this cycle, start fresh after backoff

                except Exception:
                    elapsed = time.monotonic() - scrape_start
                    logger.exception(
                        "[%s] scrape failed after %.1f s — skipping to next item.",
                        item.item_name, elapsed,
                    )
                    with get_session() as session:
                        run = session.get(ScrapeRun, run_id)
                        finish_scrape_run(
                            session, run,
                            items_attempted=1, items_succeeded=0,
                            location_lookups_performed=0,
                            status="interrupted",
                        )
                    continue

                # ── Success ───────────────────────────────────────────────
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

                logger.info(
                    "[%s] %.1f s — %d listing(s), %d fresh location(s).",
                    item.item_name, elapsed, obs_count, lookups,
                )

                # Rollup after every item finishes scraping, so analytics tables
                # stay fresh within a cycle instead of waiting for the next day.
                today = datetime.now().date()
                with get_session() as session:
                    try:
                        run_rollup_for_date(session, today)
                        session.commit()
                        logger.info("Rollup complete for %s.", today)
                    except Exception:
                        logger.exception("Rollup failed.")

                # Per-item watch-rule check, so tracked items with an active WatchRule
                # get evaluated immediately after they finish scraping instead of
                # waiting for the end-of-cycle check.
                item_aliases = {item.item_name.strip().lower()}
                if item.display_name:
                    item_aliases.add(item.display_name.strip().lower())
                try:
                    with get_session() as session:
                        _notif_cfg = get_notification_settings(session)
                        await check_watch_rules(session, provider, notifier, _notif_cfg, only_item_aliases=item_aliases)
                except RateLimitError:
                    logger.warning("Rate limited during per-item watch-rule check for '%s' — skipping.", item.item_name)
                except Exception:
                    logger.exception("Unhandled error in per-item watch-rule check for '%s'.", item.item_name)

                # Inter-item delay (skip after the last item).
                is_last = (i == len(items) - 1)
                if not is_last and cfg.item_delay_seconds > 0 and not stop_event.is_set():
                    logger.debug("Inter-item delay: %.1f s.", cfg.item_delay_seconds)
                    await asyncio.sleep(cfg.item_delay_seconds)

            if stop_event.is_set():
                break

            # ── Watch rules (after full cycle, before sleep) ──────────────
            if not rate_limited_this_cycle:
                try:
                    with get_session() as session:
                        _notif_cfg = get_notification_settings(session)
                        await check_watch_rules(session, provider, notifier, _notif_cfg, exclude_item_aliases=tracked_item_aliases)
                except RateLimitError:
                    logger.warning("Rate limited during watch-rules check — skipping.")
                except Exception:
                    logger.exception("Unhandled error in watch-rules check.")

            # ── IP auto-rotation bookkeeping ──────────────────────────────
            if not rate_limited_this_cycle:
                if total_location_attempts_this_cycle > 0 and total_location_successes_this_cycle == 0:
                    consecutive_bad_cycles += 1
                    logger.warning(
                        "Bad cycle: all %d location lookup attempt(s) failed this cycle "
                        "(0 successes) (consecutive bad cycles: %d/%d).",
                        total_location_attempts_this_cycle, consecutive_bad_cycles,
                        CONSECUTIVE_BAD_CYCLES_THRESHOLD,
                    )
                    if consecutive_bad_cycles >= CONSECUTIVE_BAD_CYCLES_THRESHOLD:
                        logger.warning(
                            "%d consecutive bad cycles — triggering automatic IP rotation.",
                            consecutive_bad_cycles,
                        )
                        try:
                            async with httpx.AsyncClient() as client:
                                resp = await client.post(_ROTATE_IP_URL, timeout=10)
                            logger.warning(
                                "Auto IP-rotation request sent: HTTP %d — %s",
                                resp.status_code, resp.text,
                            )
                        except Exception:
                            logger.exception("Auto IP-rotation request failed.")
                        consecutive_bad_cycles = 0
                        logger.info("Consecutive bad-cycle streak reset after triggering rotation.")
                elif consecutive_bad_cycles > 0:
                    logger.info(
                        "Cycle OK (%d/%d location lookup(s) succeeded) — resetting bad-cycle "
                        "streak (was %d).",
                        total_location_successes_this_cycle, total_location_attempts_this_cycle,
                        consecutive_bad_cycles,
                    )
                    consecutive_bad_cycles = 0

            # ── Cycle sleep ───────────────────────────────────────────────
            if not rate_limited_this_cycle:
                cycle_elapsed = time.monotonic() - cycle_start
                sleep_for = max(0.0, cfg.poll_interval_seconds - cycle_elapsed)
                logger.info(
                    "Cycle complete in %.1f s. Sleeping %.1f s before next cycle.",
                    cycle_elapsed, sleep_for,
                )
                with get_session() as session:
                    set_collector_status(
                        session,
                        state="sleeping",
                        next_cycle_at=datetime.now() + timedelta(seconds=sleep_for),
                    )
                await _interruptible_sleep(sleep_for, stop_event)

    except KeyboardInterrupt:
        logger.info("Collector stopped (KeyboardInterrupt).")
    finally:
        await provider.teardown()
        await notifier.close()


if __name__ == "__main__":
    asyncio.run(main())
