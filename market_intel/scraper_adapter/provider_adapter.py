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
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable

import httpx
from playwright.async_api import Page
from sqlalchemy import select
from sqlalchemy.orm import Session

from playwright_provider import (
    ITEM_CARD,
    LOADING_SPINNER,
    NO_RESULTS_SELECTOR,
    PlaywrightProvider,
    RateLimitError,
)
from parser import parse_price_text

from db.models import ListingObservation
from db.repository import (
    get_collector_status,
    get_shops_missing_location,
    log_collector_action,
    set_collector_status,
    upsert_shop_location,
)
from scraper_adapter.location_action import (
    LocationActionRecipe,
    ShopLocationDetail,
    build_location_recipe_from_request,
    fetch_shop_location,
    fetch_shop_location_via_action,
)
from settings import settings

logger = logging.getLogger(__name__)


class PageLoadStallError(Exception):
    """Raised when a listing page never renders item cards NOR the "no results" UI, even
    after retrying navigation -- i.e. the page failed to load rather than genuinely having
    zero results. Must NOT be treated as a normal empty listing (see _scrape_page)."""

# After this many consecutive location-lookup failures within one item, stop trying for the
# rest of that item's listings rather than retrying every remaining one at full timeout --
# guards against one stuck modal/overlay cascading into burning the whole cycle's time budget.
LOCATION_FAILURE_CIRCUIT_BREAKER = 4

# Total attempts (1 initial + retries) for a brand-new (never-cached) shop's location modal,
# each retry preceded by a page reload -- guards against a one-off render glitch permanently
# blacklisting a shop we've genuinely never seen before, before we flip modal_429ed.
NEW_SHOP_LOCATION_MAX_ATTEMPTS = 3

# How long to wait for at least one stylesheet to actually have parsed CSS rules before
# treating the page as "loaded" -- guards against the page being reachable and its listing
# text already visible (server-rendered), but the CSS/JS bundle not finished loading, which
# leaves card click handlers unattached (see _wait_for_css_ready).
CSS_READY_TIMEOUT_MS = 5_000

# Shared between the Playwright browser context (scrape_item) and the plain-HTTP raw-HTML
# fallback (_fetch_raw_html) so the site sees an identical client fingerprint either way.
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def _wait_for_css_ready(page: Page, timeout_ms: int = CSS_READY_TIMEOUT_MS) -> bool:
    """Poll until at least one stylesheet has actually parsed CSS rules, or timeout.

    Listing text renders from server-side HTML and is scrapable immediately, independent of
    CSS/JS. But interactive features (the location modal) depend on React having hydrated --
    which depends on the JS bundle, which loads alongside the CSS. An unstyled screenshot at
    modal-failure time (confirmed via debug_captures/modal_failures/) with zero modal/dialog
    elements in the DOM, on a page that never navigated away, points at exactly this: the page
    never became interactive, so the card's click handler was never attached in the first place.
    """
    try:
        await page.wait_for_function(
            """() => Array.from(document.styleSheets).some(s => {
                try { return s.cssRules && s.cssRules.length > 0; } catch (e) { return false; }
            })""",
            timeout=timeout_ms,
        )
        return True
    except Exception:
        return False


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


_TRAILING_SUFFIX_RE = re.compile(r"\s*(\+\d+|\([^()]*\))$")


def _base_search_term(name: str) -> str:
    """Strip trailing refine (" +7") and parenthetical (" (Capa)") suffixes so the
    resulting term is safe to send as the site's ``searchWord`` query param -- the site
    errors on those special-character suffixes. Only trailing occurrences are stripped
    (repeatedly, so "Item +7 (Capa)" fully reduces to "Item"); words in the middle of the
    name (e.g. roman numerals like "II") are left untouched.

    This must be used ONLY for building the search URL -- exact-match filtering against
    scraped card names must keep using the original, unstripped ``name``.
    """
    stripped = name
    while True:
        new_stripped = _TRAILING_SUFFIX_RE.sub("", stripped)
        if new_stripped == stripped:
            return stripped
        stripped = new_stripped


def _build_listing_page_url(
    item_name: str, store_type: str, server_type: str, sort: str, page_num: int,
) -> str:
    """Build the listing-search URL -- shared by the Playwright navigation in `_scrape_page`
    and the plain-HTTP raw-HTML fallback (`_fetch_raw_html`), so both hit the exact same
    endpoint/query string."""
    from urllib.parse import quote
    from playwright_provider import BASE_URL

    return (
        f"{BASE_URL}"
        f"?storeType={quote(store_type)}"
        f"&serverType={quote(server_type)}"
        f"&searchWord={quote(_base_search_term(item_name))}"
        f"&sortType={quote(sort)}"
        f"&limit=60"
        f"&p={page_num}"
    )


def _build_listings_from_raw(raw: list[dict], item_name: str, page_num: int) -> list[DetailedListing]:
    """Turn raw card dicts (shaped like `_DETAILED_EXTRACT_JS`'s output -- name/price/qty/
    itemId/ssi/shopName/sellerName[/domIndex]) into `DetailedListing`s, applying the exact
    same skip/parse rules regardless of whether the dicts came from the live DOM (JS
    extraction) or from parsing raw server-rendered HTML (`_RawHTMLListingParser`). Entries
    without a `domIndex` key (the raw-HTML path) naturally default to dom_index=-1, which is
    what keeps location-modal click attempts from being tried against them -- there's no
    live card to click since the browser page never actually rendered these."""
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
    return listings


_VOID_HTML_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _RawHTMLListingParser(HTMLParser):
    """Stdlib-only parser that walks raw server-rendered HTML and yields raw card dicts
    shaped exactly like `_DETAILED_EXTRACT_JS`'s client-side output, so both feed into the
    same `_build_listings_from_raw` helper. Matches CSS-module classes by substring/prefix
    (e.g. `"card_item_name" in classes`), mirroring the `[class*="..."]` selectors used
    client-side -- the hash suffixes on those classes can change per deploy.

    Used only as a last-resort fallback when the live Playwright page never rendered item
    cards after retries (see `_scrape_page`), so this deliberately favors "don't crash" over
    strictness: malformed/unexpected HTML just yields fewer (or zero) listings rather than
    raising.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.listings: list[dict] = []
        self._card: dict | None = None
        self._stack: list[dict] = []

    def handle_starttag(self, tag, attrs) -> None:
        attrs_dict = dict(attrs)
        if self._card is None:
            if tag == "li" and "data-id" in attrs_dict:
                self._card = {
                    "itemId": attrs_dict.get("data-id"),
                    "ssi": attrs_dict.get("data-ssi"),
                    "name": None,
                    "price": None,
                    "qty": None,
                    "shopName": None,
                    "sellerName": None,
                    "_detailResults": [],
                }
                self._stack = []
            return
        if tag in _VOID_HTML_TAGS:
            return
        self._stack.append({
            "tag": tag,
            "classes": attrs_dict.get("class") or "",
            "own_text": [],
            "children": [],
        })

    def handle_startendtag(self, tag, attrs) -> None:
        # Self-closed tags (e.g. `<img ... />`); default HTMLParser behavior would call
        # handle_starttag then handle_endtag anyway, but we're explicit here since our
        # handle_starttag intentionally no-ops for void tags.
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_HTML_TAGS:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._stack:
            self._stack[-1]["own_text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        if tag == "li" and not self._stack:
            # Closes the outer li[data-id] card itself (never pushed onto _stack).
            self._finish_card()
            return
        if not self._stack or self._stack[-1]["tag"] != tag:
            # Mismatched/unexpected closing tag -- ignore rather than corrupt the stack.
            return

        frame = self._stack.pop()
        text = "".join(frame["own_text"]).strip()
        if self._stack:
            self._stack[-1]["children"].append({"tag": frame["tag"], "classes": frame["classes"], "text": text})
        self._capture_frame(frame["tag"], frame["classes"], text, frame["children"])

    def _capture_frame(self, tag: str, classes: str, text: str, children: list[dict]) -> None:
        card = self._card
        if card is None:
            return

        if "card_item_name" in classes and card["name"] is None:
            card["name"] = text

        if "card_item_price" in classes:
            span_child = next((c for c in children if c["tag"] == "span"), None)
            if span_child is not None:
                card["price"] = span_child["text"]

        if "card_detail_info_result" in classes:
            card["_detailResults"].append(text)

        if tag == "li" and "card_shop_info__" in classes:
            spans = [c for c in children if c["tag"] == "span"]
            if len(spans) >= 2:
                label, value = spans[0]["text"], spans[1]["text"]
                # "Nome do Comércio" -- watch for mangled encoding ("rcio"/"Com\xe9rcio").
                if "rcio" in label:
                    card["shopName"] = value
                elif "Vendedor" in label:
                    card["sellerName"] = value

    def _finish_card(self) -> None:
        card = self._card
        self._card = None
        self._stack = []
        if card is None:
            return
        detail_results = card.pop("_detailResults")
        card["qty"] = detail_results[1] if len(detail_results) >= 2 else None
        self.listings.append(card)


def _parse_raw_html_listings(html: str, item_name: str, page_num: int) -> list[DetailedListing]:
    """Parse raw server-rendered HTML (no JS/CSS) into `DetailedListing`s -- the fallback
    path used when the live Playwright page stalls (see `_scrape_page`)."""
    parser = _RawHTMLListingParser()
    try:
        parser.feed(html)
    except Exception:
        logger.warning("Raw-HTML fallback parser failed for '%s' page %d.", item_name, page_num, exc_info=True)
        return []
    return _build_listings_from_raw(parser.listings, item_name, page_num)


async def _fetch_raw_html(
    item_name: str, store_type: str, server_type: str, sort: str, page_num: int, timeout: float,
) -> str | None:
    """Plain HTTP GET of the same listing-search URL Playwright navigates to, bypassing the
    browser/JS/CSS entirely -- the site's initial HTML response already contains full
    listing data server-rendered, so this works as a fallback when the browser page itself
    fails to ever render (e.g. sustained HTTP 429 throttling breaking the Playwright page).
    Returns the response body on HTTP 200, or ``None`` (logging a warning) otherwise --
    never raises, since this is only ever called right before giving up anyway."""
    url = _build_listing_page_url(item_name, store_type, server_type, sort, page_num)
    try:
        async with httpx.AsyncClient(timeout=timeout / 1000) as client:
            response = await client.get(
                url,
                headers={"User-Agent": _BROWSER_USER_AGENT, "Accept-Language": "pt-BR"},
            )
    except Exception as exc:
        logger.warning("Raw-HTML fallback GET failed for '%s' page %d: %s", item_name, page_num, exc)
        return None

    if response.status_code != 200:
        logger.warning(
            "Raw-HTML fallback GET for '%s' page %d returned HTTP %d.",
            item_name, page_num, response.status_code,
        )
        return None
    return response.text


class DetailedListingProvider(PlaywrightProvider):
    """Same lifecycle/navigation as PlaywrightProvider; richer per-card extraction."""

    # Set True during scrape_item() if this item's location circuit breaker tripped
    # (consecutive_location_failures >= LOCATION_FAILURE_CIRCUIT_BREAKER). Reset at the
    # start of every scrape_item() call. Read by the collector runner after each item to
    # accumulate a per-cycle "bad item" count for IP-rotation heuristics.
    last_item_hit_circuit_breaker: bool = False

    async def _scrape_page(
        self,
        page: Page,
        item_name: str,
        store_type: str,
        server_type: str,
        sort: str,
        page_num: int,
    ) -> list[DetailedListing]:
        url = _build_listing_page_url(item_name, store_type, server_type, sort, page_num)
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

        content_wait_attempts = 3
        for content_attempt in range(1, content_wait_attempts + 1):
            try:
                await page.wait_for_selector(
                    f"{ITEM_CARD}, {NO_RESULTS_SELECTOR}",
                    state="attached",
                    timeout=self.timeout,
                )
                break
            except Exception as exc:
                level = logger.debug if page_num > 1 else logger.warning
                level(
                    "Timed out waiting for content on page %d (attempt %d/%d): %s",
                    page_num, content_attempt, content_wait_attempts, exc,
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=10_000)
                except Exception:
                    pass

                try:
                    no_results_present = await page.locator(NO_RESULTS_SELECTOR).count() > 0
                except Exception:
                    no_results_present = False
                try:
                    item_card_present = await page.locator(ITEM_CARD).count() > 0
                except Exception:
                    item_card_present = False

                if no_results_present or item_card_present:
                    # Content did show up despite the wait_for_selector timeout (e.g. slow
                    # networkidle settle) -- proceed normally below.
                    break

                if content_attempt == content_wait_attempts:
                    # Last resort before giving up entirely: a plain HTTP GET of the exact
                    # same URL, bypassing the browser/JS/CSS -- the site's initial HTML
                    # response is server-rendered and already contains full listing data, so
                    # this can recover a scrape even when sustained 429 throttling has broken
                    # the Playwright page itself.
                    raw_html = await _fetch_raw_html(
                        item_name, store_type, server_type, sort, page_num, self.timeout,
                    )
                    fallback_listings: list[DetailedListing] = []
                    if raw_html:
                        fallback_listings = _parse_raw_html_listings(raw_html, item_name, page_num)
                    if fallback_listings:
                        logger.warning(
                            "Page %d for '%s' never rendered via Playwright after %d attempts "
                            "-- raw-HTML fallback recovered %d listing(s).",
                            page_num, item_name, content_wait_attempts, len(fallback_listings),
                        )
                        return fallback_listings

                    raise PageLoadStallError(
                        f"Page {page_num} for '{item_name}' never rendered item cards or the "
                        f"'no results' UI after {content_wait_attempts} attempts -- treating as "
                        f"a failed scrape rather than a genuine empty result."
                    )

                await asyncio.sleep(2**content_attempt)
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=self.timeout)
                except Exception:
                    logger.debug(
                        "Reload before content-wait retry failed for page %d.", page_num,
                        exc_info=True,
                    )

        try:
            if await page.locator(NO_RESULTS_SELECTOR).count() > 0:
                logger.debug("No results for '%s' on page %d", item_name, page_num)
                return []
        except Exception:
            pass

        # Guard against proceeding to modal-click interactions later on a page whose CSS/JS
        # bundle hasn't actually finished loading -- listing text is already scrapable (SSR),
        # but every location-modal click would silently fail since React never hydrated far
        # enough to attach the card's click handler. One reload-and-recheck, done here before
        # any listing/dom_index has been captured, so there's no risk of index mismatch.
        if not await _wait_for_css_ready(page):
            logger.warning(
                "Page %d for '%s' has no CSS rules applied after %d ms -- reloading once "
                "before extraction.", page_num, item_name, CSS_READY_TIMEOUT_MS,
            )
            try:
                await page.reload(wait_until="domcontentloaded", timeout=self.timeout)
                await page.wait_for_selector(
                    f"{ITEM_CARD}, {NO_RESULTS_SELECTOR}", state="attached", timeout=self.timeout,
                )
                if not await _wait_for_css_ready(page):
                    logger.warning(
                        "Page %d for '%s' still has no CSS after reload -- proceeding anyway.",
                        page_num, item_name,
                    )
            except Exception:
                logger.debug("Reload after CSS-not-ready check failed for page %d.", page_num, exc_info=True)

        try:
            raw: list[dict] = await page.evaluate(_DETAILED_EXTRACT_JS)
        except Exception as exc:
            logger.warning("JS evaluation failed on page %d: %s", page_num, exc)
            return []

        listings = _build_listings_from_raw(raw, item_name, page_num)
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
        session: Session | None = None,
        tracked_item_id: int | None = None,
    ) -> list[tuple[DetailedListing, ShopLocationDetail | None, str | None]]:
        """Scrape an item's listings and, for any listing where ``needs_location`` returns
        True (i.e. its (seller, shop) pair is a cache-miss), click through to read its
        location modal -- all within the same page session, since clicking requires the
        live DOM element. Listings where ``needs_location`` is False are left with a
        ``None`` location; the caller is expected to fill that in from its cache.

        Each result is a ``(listing, location, location_source_override)`` tuple.
        ``location_source_override`` is ``"pending_api"`` when the modal lookup failed for a
        brand-new shop and is being deferred to the direct-POST pass (see
        ``_run_deferred_location_pass``); ``None`` otherwise, leaving the caller's normal
        cache/fresh-lookup source logic in charge.

        ``session`` (when provided) is used to read/update the collector's ``modal_429ed``
        flag and to run the deferred direct-POST pass for previously-pending shops. Location
        clicks always use the click-based ``fetch_shop_location`` -- the direct-POST method
        (``fetch_shop_location_via_action``) is never used inline anymore; it's reserved for
        the deferred pass below, using the recipe captured (but no longer consumed inline)
        from the request listener.

        ``tracked_item_id`` (when provided, alongside ``session``) is attached to the
        ``collector_action_log`` rows written for click attempts/retries/successes and
        modal_429ed transitions, so the debug log can be filtered per tracked item.
        """
        self.last_item_hit_circuit_breaker = False
        self.last_item_location_attempts = 0

        modal_429ed = False
        if session is not None:
            status = get_collector_status(session)
            modal_429ed = bool(status.modal_429ed) if status else False

        context = await self._browser.new_context(
            user_agent=_BROWSER_USER_AGENT,
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
        )
        try:
            page = await context.new_page()
            results: list[tuple[DetailedListing, ShopLocationDetail | None, str | None]] = []

            # Ring buffer of recent console errors / uncaught exceptions, so a modal failure's
            # diagnostics capture can show *why* the page's JS bundle might not have loaded --
            # e.g. a chunk 404 or a script error -- instead of just "nothing happened."
            console_errors: list[str] = []

            def _on_console(msg) -> None:
                if msg.type == "error":
                    console_errors.append(f"console.error: {msg.text}")
                    del console_errors[:-20]

            def _on_page_error(exc) -> None:
                console_errors.append(f"pageerror: {exc}")
                del console_errors[:-20]

            page.on("console", _on_console)
            page.on("pageerror", _on_page_error)

            # Captured lazily from the first click this item that actually triggers the site's
            # location Server Action -- see LocationActionRecipe. Once set, every remaining
            # listing on this item is resolved via a direct POST instead of a click, since only
            # `ssi` is listing-specific (confirmed via live recon).
            location_recipe = None

            def _on_request(req) -> None:
                nonlocal location_recipe
                if location_recipe is None:
                    recipe = build_location_recipe_from_request(req)
                    if recipe is not None:
                        location_recipe = recipe

            page.on("request", _on_request)

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
                    location_source_override: str | None = None
                    if (
                        not location_lookups_disabled
                        and listing.dom_index >= 0
                        and needs_location(listing)
                    ):
                        self.last_item_location_attempts += 1

                        if modal_429ed:
                            # The flag is already up from an earlier hard failure this cycle --
                            # a single soft-probe click (no reload-retry loop) tells us whether
                            # the block has cleared, without hammering the site while it's stuck.
                            if session is not None:
                                log_collector_action(
                                    session, action="click_attempt", tracked_item_id=tracked_item_id,
                                    item_name=item_name, ssi=listing.ssi,
                                    seller_name=listing.seller_name, shop_name=listing.shop_name,
                                )
                            location = await fetch_shop_location(
                                page, card_locator.nth(listing.dom_index),
                                item_name=item_name, seller_name=listing.seller_name,
                                shop_name=listing.shop_name, console_errors=console_errors,
                                session=session, tracked_item_id=tracked_item_id,
                            )
                            if location is not None:
                                modal_429ed = False
                                consecutive_location_failures = 0
                                if session is not None:
                                    log_collector_action(
                                        session, action="click_success", tracked_item_id=tracked_item_id,
                                        item_name=item_name, ssi=listing.ssi,
                                        seller_name=listing.seller_name, shop_name=listing.shop_name,
                                    )
                                    log_collector_action(
                                        session, action="modal_429ed_cleared",
                                        tracked_item_id=tracked_item_id, item_name=item_name,
                                        seller_name=listing.seller_name, shop_name=listing.shop_name,
                                    )
                                    set_collector_status(
                                        session, state="scraping", current_item_name=item_name,
                                        modal_429ed=False,
                                    )
                                    session.commit()
                                logger.info(
                                    "Soft-probe location lookup succeeded for a new shop -- "
                                    "clearing modal_429ed."
                                )
                            else:
                                location_source_override = "pending_api"
                        else:
                            # Brand-new (never-cached) shop -- worth a couple of reload-retries
                            # before giving up, since a stuck/failed render here is the one
                            # signal we use to flip modal_429ed.
                            for attempt in range(1, NEW_SHOP_LOCATION_MAX_ATTEMPTS + 1):
                                if session is not None:
                                    log_collector_action(
                                        session,
                                        action="click_attempt" if attempt == 1 else "click_retry",
                                        tracked_item_id=tracked_item_id, item_name=item_name,
                                        ssi=listing.ssi, seller_name=listing.seller_name,
                                        shop_name=listing.shop_name,
                                    )
                                location = await fetch_shop_location(
                                    page, card_locator.nth(listing.dom_index),
                                    item_name=item_name, seller_name=listing.seller_name,
                                    shop_name=listing.shop_name, console_errors=console_errors,
                                    session=session, tracked_item_id=tracked_item_id,
                                )
                                if location is not None:
                                    if session is not None:
                                        log_collector_action(
                                            session, action="click_success",
                                            tracked_item_id=tracked_item_id, item_name=item_name,
                                            ssi=listing.ssi, seller_name=listing.seller_name,
                                            shop_name=listing.shop_name,
                                        )
                                    break
                                if attempt == NEW_SHOP_LOCATION_MAX_ATTEMPTS:
                                    break
                                logger.warning(
                                    "Location modal failed for new shop (seller=%s shop=%s), "
                                    "attempt %d/%d -- reloading page before retry.",
                                    listing.seller_name, listing.shop_name, attempt,
                                    NEW_SHOP_LOCATION_MAX_ATTEMPTS,
                                )
                                try:
                                    await page.reload(wait_until="domcontentloaded", timeout=self.timeout)
                                    await page.wait_for_selector(
                                        f"{ITEM_CARD}, {NO_RESULTS_SELECTOR}",
                                        state="attached", timeout=self.timeout,
                                    )
                                except Exception:
                                    logger.debug("Reload before location retry failed.", exc_info=True)
                                card_locator = page.locator(ITEM_CARD)

                            if location is None:
                                consecutive_location_failures += 1
                                location_source_override = "pending_api"
                                if not modal_429ed:
                                    modal_429ed = True
                                    logger.warning(
                                        "Location modal failed %d/%d times for a new shop "
                                        "(seller=%s shop=%s) -- setting modal_429ed and deferring "
                                        "to the direct-POST pass.",
                                        NEW_SHOP_LOCATION_MAX_ATTEMPTS, NEW_SHOP_LOCATION_MAX_ATTEMPTS,
                                        listing.seller_name, listing.shop_name,
                                    )
                                    if session is not None:
                                        log_collector_action(
                                            session, action="modal_429ed_set",
                                            tracked_item_id=tracked_item_id, item_name=item_name,
                                            seller_name=listing.seller_name, shop_name=listing.shop_name,
                                        )
                                        set_collector_status(
                                            session, state="scraping", current_item_name=item_name,
                                            modal_429ed=True,
                                        )
                                        session.commit()
                                if consecutive_location_failures >= LOCATION_FAILURE_CIRCUIT_BREAKER:
                                    logger.warning(
                                        "%d consecutive location lookup failures for '%s' -- "
                                        "skipping location lookups for the rest of this item "
                                        "(page may be stuck).",
                                        consecutive_location_failures, item_name,
                                    )
                                    location_lookups_disabled = True
                                    self.last_item_hit_circuit_breaker = True
                            else:
                                consecutive_location_failures = 0

                        # Throttle between modal clicks -- avoids hammering the site with
                        # rapid-fire interactions, a likely contributor to HTTP 429s.
                        if not location_lookups_disabled:
                            delay = location_click_delay_seconds if location_click_delay_seconds is not None else settings.location_click_delay_seconds
                            await asyncio.sleep(delay)
                    results.append((listing, location, location_source_override))

            if session is not None:
                await self._run_deferred_location_pass(
                    context, session, server_type, location_recipe,
                )

            return results
        finally:
            await context.close()

    async def _run_deferred_location_pass(
        self, context, session: Session, server_name: str,
        location_recipe: LocationActionRecipe | None,
    ) -> None:
        """Resolve locations for shops flagged ``location_source="pending_api"`` in earlier
        cycles, via a direct POST (no click, no modal) instead of the click-based method --
        runs once per item scrape, only when it's actually safe/useful: the ``modal_429ed``
        flag is currently off, a recipe was captured this session (from a real click earlier
        in this item or a previous one), and there's pending work for this server.

        ``get_shops_missing_location`` only returns (seller_name, shop_name) pairs -- no
        ``ssi``, which the direct-POST recipe requires. Rather than adding new DB surface for
        this, we reuse the most recent ``ListingObservation.ssi`` recorded for that shop on
        this server (any listing that shop has sold recently carries a still-valid ssi for
        the site's location endpoint, per the recipe's own docs: only ``ssi`` is
        listing-specific, ``svrId``/``mapId`` are not).
        """
        if location_recipe is None:
            return
        status = get_collector_status(session)
        if status and status.modal_429ed:
            return

        pending = get_shops_missing_location(session, server_name)
        if not pending:
            return

        for seller_name, shop_name in pending:
            ssi = session.scalars(
                select(ListingObservation.ssi)
                .where(
                    ListingObservation.seller_name == seller_name,
                    ListingObservation.shop_name == shop_name,
                    ListingObservation.server_name == server_name,
                    ListingObservation.ssi.is_not(None),
                )
                .order_by(ListingObservation.observed_at.desc())
                .limit(1)
            ).first()
            if not ssi:
                continue

            try:
                location = await fetch_shop_location_via_action(context.request, location_recipe, ssi)
            except RateLimitError:
                logger.warning(
                    "Deferred location pass hit a rate limit -- stopping for this cycle "
                    "(seller=%s shop=%s); will retry next cycle.", seller_name, shop_name,
                )
                return

            if location is not None:
                upsert_shop_location(
                    session, seller_name=seller_name, shop_name=shop_name, server_name=server_name,
                    map_id=None, map_name=location.map_name, x_pos=location.x_pos, y_pos=location.y_pos,
                )
                session.commit()
                logger.info(
                    "Deferred location pass resolved seller=%s shop=%s via direct POST.",
                    seller_name, shop_name,
                )
