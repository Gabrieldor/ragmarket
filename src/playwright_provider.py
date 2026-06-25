"""Playwright (headless Chrome) data provider.

Selected method: Playwright
Reason: The site uses Next.js with dynamic content loading and
        browser-fingerprinting checks that make plain HTTP requests
        unreliable.  Playwright runs a real Chromium instance and fully
        executes JavaScript, guaranteeing that all listing data is rendered
        before scraping begins.

All CSS selectors are isolated in the SELECTORS block below so that future
site changes require edits in exactly one place.
"""

import asyncio
import logging
from typing import Optional
from urllib.parse import quote

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

from data_provider import DataProvider, Listing
from parser import parse_price_text

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised when the site responds with HTTP 429 Too Many Requests."""

# ── URL ───────────────────────────────────────────────────────────────────────
BASE_URL = "https://ro.gnjoylatam.com/pt/intro/shop-search/trading"

# ── SELECTORS ─────────────────────────────────────────────────────────────────
# Edit only this section when the site updates its HTML/CSS.

# Each listing card — stable because it uses a data attribute.
ITEM_CARD = "li[data-id]"

# Item name element inside each card.
NAME_SELECTOR = "[class*='card_item_name']"

# Price <span> inside each card.
# Matches "card_item_price__<hash>" regardless of the hash suffix.
PRICE_SELECTOR = "[class*='card_item_price'] span"

# Loading GIF that appears while data is being fetched.
LOADING_SPINNER = "img[src*='loading-gif']"

# Element shown when the search returns zero results.
NO_RESULTS_SELECTOR = "[class*='fallback_ui'], [class*='no_result'], [class*='empty_result']"

# ── SELECTORS END ─────────────────────────────────────────────────────────────

# JavaScript that extracts price text and quantity from every card on the page
# in a single DOM pass — more efficient than one Playwright call per card.
_EXTRACT_JS = """
() => {
    const cards = document.querySelectorAll('li[data-id]');
    return Array.from(cards).map(card => {
        const nameEl  = card.querySelector('[class*="card_item_name"]');
        const priceEl = card.querySelector('[class*="card_item_price"] span');

        // The bottom section has two detail rows: [0] = type, [1] = quantity.
        const detailResults = card.querySelectorAll(
            '[class*="card_shop_card_bottom"] [class*="card_detail_info_result"]'
        );
        const qtyEl = detailResults.length >= 2 ? detailResults[1] : null;

        return {
            name:  nameEl  ? nameEl.textContent.trim()  : null,
            price: priceEl ? priceEl.textContent.trim() : null,
            qty:   qtyEl   ? qtyEl.textContent.trim()   : null,
        };
    });
}
"""


class PlaywrightProvider(DataProvider):
    def __init__(self, headless: bool = True, timeout: int = 30_000, page_delay: float = 3.0) -> None:
        self.headless = headless
        self.timeout = timeout
        self.page_delay = page_delay
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    async def setup(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        logger.info("Playwright browser started (headless=%s)", self.headless)

    async def teardown(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Playwright browser stopped")

    async def get_listings(
        self,
        item_name: str,
        store_type: str = "BUY",
        server_type: str = "FREYA",
        sort: str = "RELATED",
        max_pages: int = 1,
    ) -> list[Listing]:
        """Navigate to the catalog and return all visible listings."""
        context: BrowserContext = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
        )
        try:
            page: Page = await context.new_page()
            listings: list[Listing] = []

            for page_num in range(1, max_pages + 1):
                if page_num > 1:
                    logger.debug("Waiting %.1fs before page %d…", self.page_delay, page_num)
                    await asyncio.sleep(self.page_delay)
                page_listings = await self._scrape_page(
                    page, item_name, store_type, server_type, sort, page_num
                )
                listings.extend(page_listings)
                if not page_listings:
                    break  # No more results

            return listings
        finally:
            await context.close()

    async def _scrape_page(
        self,
        page: Page,
        item_name: str,
        store_type: str,
        server_type: str,
        sort: str,
        page_num: int,
    ) -> list[Listing]:
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

        # ── Navigation ────────────────────────────────────────────────────────
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
                await asyncio.sleep(2 ** attempt)

        # ── Wait for dynamic content ──────────────────────────────────────────
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
            # Pages beyond the first may simply not exist — log quietly
            level = logger.debug if page_num > 1 else logger.warning
            level("Timed out waiting for content on page %d: %s", page_num, exc)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

        # ── No-results guard ──────────────────────────────────────────────────
        try:
            if await page.locator(NO_RESULTS_SELECTOR).count() > 0:
                logger.debug("No results for '%s' on page %d", item_name, page_num)
                return []
        except Exception:
            pass

        # ── Extract listings via a single JS evaluation ───────────────────────
        try:
            raw: list[dict] = await page.evaluate(_EXTRACT_JS)
        except Exception as exc:
            logger.warning("JS evaluation failed on page %d: %s", page_num, exc)
            return []

        listings: list[Listing] = []
        skipped = 0
        for entry in raw:
            card_name = (entry.get("name") or "").strip()
            if card_name and card_name.lower() != item_name.lower():
                skipped += 1
                continue
            price = parse_price_text(entry.get("price") or "")
            qty   = parse_price_text(entry.get("qty")   or "")
            if price and price > 0:
                listings.append(Listing(price=price, quantity=qty or 1))

        if skipped:
            logger.debug(
                "Page %d: skipped %d non-matching card(s) for '%s'",
                page_num, skipped, item_name,
            )
        logger.debug(
            "Page %d: %d listing(s) for '%s'", page_num, len(listings), item_name
        )
        return listings
