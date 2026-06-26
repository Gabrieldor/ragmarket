"""Extends the existing PlaywrightProvider with richer per-listing extraction.

The original `playwright_provider.py` (D:\\Rag\\src) is never modified. This module
subclasses `PlaywrightProvider` and overrides only the extraction hook
(`_scrape_page`) so that browser lifecycle (`setup`/`teardown`) and the
navigation/retry loop in the inherited `get_listings()` are fully reused as-is.

The original `_EXTRACT_JS` only pulls name/price/qty. The card DOM also exposes
(confirmed via live recon, see ARCHITECTURE.md section 1):
  - data-id  -> site item id
  - data-ssi -> stable per-listing id ("ssi")
  - "Nome do Comércio" -> shop name
  - "Vendedor"          -> seller name
all without any extra request.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable

from playwright.async_api import Page

from playwright_provider import (
    ITEM_CARD,
    LOADING_SPINNER,
    NO_RESULTS_SELECTOR,
    PlaywrightProvider,
    RateLimitError,
)
from parser import parse_price_text

from scraper_adapter.location_action import ShopLocationDetail, fetch_shop_location
from settings import settings

logger = logging.getLogger(__name__)

# After this many consecutive location-lookup failures within one item, stop trying for the
# rest of that item's listings rather than retrying every remaining one at full timeout --
# guards against one stuck modal/overlay cascading into burning the whole cycle's time budget.
LOCATION_FAILURE_CIRCUIT_BREAKER = 2


@dataclass
class DetailedListing:
    price: int
    quantity: int
    item_id: int | None
    ssi: str | None
    shop_name: str | None
    seller_name: str | None
    dom_index: int = -1  # index among li[data-id] cards on the page, for location click-through


_DETAILED_EXTRACT_JS = """
() => {
    const cards = document.querySelectorAll('li[data-id]');
    return Array.from(cards).map((card, domIndex) => {
        const nameEl  = card.querySelector('[class*="card_item_name"]');
        const priceEl = card.querySelector('[class*="card_item_price"] span');

        const detailResults = card.querySelectorAll(
            '[class*="card_shop_card_bottom"] [class*="card_detail_info_result"]'
        );
        const qtyEl = detailResults.length >= 2 ? detailResults[1] : null;

        let shopName = null, sellerName = null;
        const infoItems = card.querySelectorAll('[class*="card_shop_info__"]');
        infoItems.forEach(li => {
            const spans = li.querySelectorAll('span');
            if (spans.length < 2) return;
            const label = spans[0].textContent.trim();
            const value = spans[1].textContent.trim();
            if (label.indexOf('rcio') !== -1) shopName = value;   // "Nome do Comércio"
            if (label.indexOf('Vendedor') !== -1) sellerName = value;
        });

        return {
            name: nameEl ? nameEl.textContent.trim() : null,
            price: priceEl ? priceEl.textContent.trim() : null,
            qty: qtyEl ? qtyEl.textContent.trim() : null,
            itemId: card.getAttribute('data-id'),
            ssi: card.getAttribute('data-ssi'),
            shopName,
            sellerName,
            domIndex,
        };
    });
}
"""


class DetailedListingProvider(PlaywrightProvider):
    """Same lifecycle/navigation as PlaywrightProvider; richer per-card extraction."""

    async def _scrape_page(
        self,
        page: Page,
        item_name: str,
        store_type: str,
        server_type: str,
        sort: str,
        page_num: int,
    ) -> list[DetailedListing]:
        from urllib.parse import quote
        from playwright_provider import BASE_URL

        url = (
            f"{BASE_URL}"
            f"?storeType={quote(store_type)}"
            f"&serverType={quote(server_type)}"
            f"&searchWord={quote(item_name)}"
            f"&sortType={quote(sort)}"
            f"&limit=60"
            f"&p={page_num}"
        )
        logger.debug("Navigating to: %s", url)

        for attempt in range(1, 4):
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout)
                if response and response.status == 429:
                    raise RateLimitError(f"HTTP 429 received for '{item_name}' page {page_num}")
                break
            except RateLimitError:
                raise
            except Exception as exc:
                logger.debug("Navigation attempt %d failed: %s", attempt, exc)
                if attempt == 3:
                    logger.debug("Giving up on page %d after 3 attempts", page_num)
                    return []
                await asyncio.sleep(2**attempt)

        try:
            spinner = page.locator(LOADING_SPINNER)
            if await spinner.count() > 0:
                await spinner.first.wait_for(state="hidden", timeout=self.timeout)
        except Exception:
            pass

        try:
            await page.wait_for_selector(
                f"{ITEM_CARD}, {NO_RESULTS_SELECTOR}",
                state="attached",
                timeout=self.timeout,
            )
        except Exception as exc:
            level = logger.debug if page_num > 1 else logger.warning
            level("Timed out waiting for content on page %d: %s", page_num, exc)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

        try:
            if await page.locator(NO_RESULTS_SELECTOR).count() > 0:
                logger.debug("No results for '%s' on page %d", item_name, page_num)
                return []
        except Exception:
            pass

        try:
            raw: list[dict] = await page.evaluate(_DETAILED_EXTRACT_JS)
        except Exception as exc:
            logger.warning("JS evaluation failed on page %d: %s", page_num, exc)
            return []

        listings: list[DetailedListing] = []
        skipped = 0
        for entry in raw:
            card_name = (entry.get("name") or "").strip()
            if card_name and card_name.lower() != item_name.lower():
                skipped += 1
                continue
            price = parse_price_text(entry.get("price") or "")
            qty = parse_price_text(entry.get("qty") or "")
            if price and price > 0:
                item_id_raw = entry.get("itemId")
                listings.append(
                    DetailedListing(
                        price=price,
                        quantity=qty or 1,
                        item_id=int(item_id_raw) if item_id_raw else None,
                        ssi=entry.get("ssi"),
                        shop_name=entry.get("shopName"),
                        seller_name=entry.get("sellerName"),
                        dom_index=entry.get("domIndex", -1),
                    )
                )

        if skipped:
            logger.debug(
                "Page %d: skipped %d non-matching card(s) for '%s'", page_num, skipped, item_name
            )
        logger.debug("Page %d: %d detailed listing(s) for '%s'", page_num, len(listings), item_name)
        return listings

    async def get_detailed_listings(
        self,
        item_name: str,
        store_type: str = "BUY",
        server_type: str = "FREYA",
        sort: str = "LOW_PRICE",
        max_pages: int = 1,
    ) -> list[DetailedListing]:
        """Same control flow as the inherited get_listings(), typed for DetailedListing."""
        return await self.get_listings(  # type: ignore[return-value]
            item_name=item_name,
            store_type=store_type,
            server_type=server_type,
            sort=sort,
            max_pages=max_pages,
        )

    async def scrape_item(
        self,
        item_name: str,
        store_type: str,
        server_type: str,
        needs_location: Callable[[DetailedListing], bool],
        sort: str = "LOW_PRICE",
        max_pages: int = 1,
        location_click_delay_seconds: float | None = None,
    ) -> list[tuple[DetailedListing, ShopLocationDetail | None]]:
        """Scrape an item's listings and, for any listing where ``needs_location`` returns
        True (i.e. its (seller, shop) pair is a cache-miss), click through to read its
        location modal -- all within the same page session, since clicking requires the
        live DOM element. Listings where ``needs_location`` is False are left with a
        ``None`` location; the caller is expected to fill that in from its cache.
        """
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
        )
        try:
            page = await context.new_page()
            results: list[tuple[DetailedListing, ShopLocationDetail | None]] = []

            for page_num in range(1, max_pages + 1):
                if page_num > 1:
                    await asyncio.sleep(self.page_delay)
                listings = await self._scrape_page(
                    page, item_name, store_type, server_type, sort, page_num
                )
                if not listings:
                    break

                card_locator = page.locator(ITEM_CARD)
                consecutive_location_failures = 0
                location_lookups_disabled = False
                for listing in listings:
                    location: ShopLocationDetail | None = None
                    if (
                        not location_lookups_disabled
                        and listing.dom_index >= 0
                        and needs_location(listing)
                    ):
                        location = await fetch_shop_location(page, card_locator.nth(listing.dom_index))
                        if location is None:
                            consecutive_location_failures += 1
                            if consecutive_location_failures >= LOCATION_FAILURE_CIRCUIT_BREAKER:
                                logger.warning(
                                    "%d consecutive location lookup failures for '%s' -- "
                                    "skipping location lookups for the rest of this item "
                                    "(page may be stuck).",
                                    consecutive_location_failures, item_name,
                                )
                                location_lookups_disabled = True
                        else:
                            consecutive_location_failures = 0
                        # Throttle between modal clicks -- avoids hammering the site with
                        # rapid-fire interactions, a likely contributor to HTTP 429s.
                        if not location_lookups_disabled:
                            delay = location_click_delay_seconds if location_click_delay_seconds is not None else settings.location_click_delay_seconds
                            await asyncio.sleep(delay)
                    results.append((listing, location))

            return results
        finally:
            await context.close()
