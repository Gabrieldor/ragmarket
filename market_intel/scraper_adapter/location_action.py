"""Shop location lookup via UI-click simulation.

An earlier attempt called the underlying Next.js Server Action directly via a
hand-crafted POST (see ARCHITECTURE.md section 1 for the request/response
shape). That was abandoned: without replicating Next.js's full internal
header set (Next-Router-State-Tree, Accept, etc.) the server falls back to
rendering the entire page instead of executing just the action, making a
faithful direct call fragile and high-maintenance.

Clicking the card and reading the resulting modal is simpler and more
robust to internal site changes -- confirmed working via live recon against
multiple listings. This is the canonical method; there is no raw-POST
fallback to maintain.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page, Error as PlaywrightError

from notifications.rule_parser import REFINE_PREFIX_RE, SLOT_SUFFIX_RE

logger = logging.getLogger(__name__)

# Selectors isolated here, mirroring the SELECTORS block convention in
# playwright_provider.py -- edit only this block if the site's modal markup changes.
MODAL_INFO_ITEM = '[class*="style_shop_info__"]'
MODAL_WRAP = '[class*="style_shop_info_content_wrap"]'

# Forensic capture for modal failures, so a stuck/changed page can be inspected after
# the fact instead of only ever seeing a one-line "timed out" warning. Capped to avoid
# unbounded disk growth on a long-running collector.
_DEBUG_DIR = Path(__file__).resolve().parents[1] / "debug_captures" / "modal_failures"
_DEBUG_MAX_FILES = 200  # per extension (png/html) -- oldest pruned first

_DOM_PROBE_JS = """
() => ({
    modalWrapCount: document.querySelectorAll('[class*="style_shop_info_content_wrap"]').length,
    modalInfoCount: document.querySelectorAll('[class*="style_shop_info__"]').length,
    dialogCount: document.querySelectorAll('[role="dialog"]').length,
    overlayCount: document.querySelectorAll('[class*="overlay" i]').length,
})
"""


def _slug(text: str | None, max_len: int = 40) -> str:
    if not text:
        return "unknown"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", text.strip())
    return slug[:max_len] or "unknown"


def _prune_old_captures() -> None:
    for ext in ("*.png", "*.html"):
        files = sorted(_DEBUG_DIR.glob(ext), key=lambda p: p.stat().st_mtime)
        excess = len(files) - _DEBUG_MAX_FILES
        for f in files[:max(excess, 0)]:
            try:
                f.unlink()
            except OSError:
                pass


async def _capture_failure_diagnostics(
    page: Page, reason: str, item_name: str | None, seller_name: str | None, shop_name: str | None,
) -> None:
    """Best-effort forensic capture on a modal failure -- screenshot, full HTML, and a
    quick DOM probe (element counts for the selectors we rely on), so a future failure
    can be diagnosed from artifacts instead of needing to reproduce it live. Every step
    is independently swallowed: a broken capture must never fail the actual scrape.
    """
    probe = {}
    try:
        probe = await page.evaluate(_DOM_PROBE_JS)
    except Exception:
        pass

    url = None
    try:
        url = page.url
    except Exception:
        pass

    logger.warning(
        "Modal failure diagnostics [%s]: item=%s seller=%s shop=%s url=%s dom_probe=%s",
        reason, item_name, seller_name, shop_name, url, probe,
    )

    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        base_name = f"{stamp}_{_slug(item_name)}_{_slug(seller_name)}"
        png_path = _DEBUG_DIR / f"{base_name}.png"
        html_path = _DEBUG_DIR / f"{base_name}.html"
        try:
            await page.screenshot(path=str(png_path))
        except Exception:
            logger.debug("Failed to save failure screenshot.", exc_info=True)
        try:
            html = await page.content()
            html_path.write_text(html, encoding="utf-8")
        except Exception:
            logger.debug("Failed to save failure HTML dump.", exc_info=True)
        _prune_old_captures()
    except Exception:
        logger.debug("Failure-diagnostics capture setup failed.", exc_info=True)

_EXTRACT_MODAL_JS = """
() => {
    const items = document.querySelectorAll('[class*="style_shop_info__"]');
    const result = {};
    items.forEach(li => {
        const label = li.querySelector('span');
        const nameEl = li.querySelector('[class*="style_shop_info_content_name__"]');
        if (!label || !nameEl) return;
        const clone = nameEl.cloneNode(true);
        const coordSpan = clone.querySelector('span');
        const coords = coordSpan ? coordSpan.textContent.trim() : null;
        if (coordSpan) coordSpan.remove();
        result[label.textContent.trim()] = { value: clone.textContent.trim(), coords };
    });
    // Not `document.querySelector('h3')` -- that grabs the first <h3> in the whole
    // document, which is a background search-card title (no refine/slot prefix) since
    // the modal renders on top of, not instead of, the card list. The modal's own item
    // name (with "+7"/"[1]" prefix/suffix) lives in this more specific class instead.
    const titleEl = document.querySelector('[class*="style_item_name__"]');
    result.itemNameTitle = titleEl ? titleEl.textContent.trim() : null;
    return result;
}
"""


def parse_item_name_title(text: str | None) -> tuple[int | None, int | None]:
    """Extract ``(actual_refine, actual_slot)`` from a modal's item-name title text,
    e.g. ``"+7Sapatos do Lobo Cinzento"`` -> ``(7, None)`` or
    ``"Sapatos do Lobo Cinzento [1]"`` -> ``(None, 1)``.

    Uses the same leading ``+N`` / trailing ``[N]`` patterns as
    notifications.rule_parser.parse_rule so a rule's ``required_refine``/``required_slot``
    can be compared directly against a listing's actual modal title.
    """
    if not text:
        return None, None

    actual_refine: int | None = None
    refine_match = REFINE_PREFIX_RE.match(text)
    if refine_match:
        actual_refine = int(refine_match.group(1))

    actual_slot: int | None = None
    slot_match = SLOT_SUFFIX_RE.search(text)
    if slot_match:
        actual_slot = int(slot_match.group(1))

    return actual_refine, actual_slot


class ShopLocationDetail:
    def __init__(
        self, map_name: str | None, x_pos: int | None, y_pos: int | None, seller_name: str | None,
        server_name: str | None, item_name_title: str | None = None,
    ):
        self.map_name = map_name
        self.x_pos = x_pos
        self.y_pos = y_pos
        self.seller_name = seller_name
        self.server_name = server_name
        self.item_name_title = item_name_title


def _parse_coords(coords: str | None) -> tuple[int | None, int | None]:
    if not coords or "/" not in coords:
        return None, None
    x_str, _, y_str = coords.partition("/")
    try:
        return int(x_str.strip()), int(y_str.strip())
    except ValueError:
        return None, None


async def _force_close_any_overlay(page: Page) -> None:
    """Best-effort cleanup after a failed modal interaction.

    The modal is a Radix UI dialog with a separate overlay element that
    intercepts all clicks while open. If the dialog content never finished
    rendering (e.g. a slow/failed detail fetch), Escape alone can leave that
    overlay stuck -- which then blocks every subsequent click on the page,
    turning one failed lookup into a cascade of failures for every remaining
    listing. Escape first, then a click on an empty corner of the viewport as
    a second dismissal attempt, swallowing all errors either way.
    """
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
    except Exception:
        pass
    try:
        await page.mouse.click(2, 2)
        await page.wait_for_timeout(200)
    except Exception:
        pass


async def fetch_shop_location(
    page: Page, card_locator, timeout_ms: int = 8_000,
    *, item_name: str | None = None, seller_name: str | None = None, shop_name: str | None = None,
) -> ShopLocationDetail | None:
    """Click a single result card and read its location modal.

    ``card_locator`` is a Playwright Locator pointing at exactly one ``li[data-id]``
    element on the currently-loaded results page. Closes the modal before
    returning, leaving the page ready for the next card. ``timeout_ms`` is
    deliberately short (modals render in ~1s under normal conditions per live
    testing) so a stuck attempt fails fast rather than blocking for the full
    page-navigation timeout.

    If the card click triggers a full page navigation (the site changed its
    frontend so that clicking a listing card reloads the page instead of
    opening a modal), we detect it immediately via a framenavigated listener
    and return None without burning timeout waiting for a modal that won't appear.
    Each accidental navigation = one extra HTTP GET, so catching it early
    prevents the rate limiter from seeing a burst of full page loads.
    """
    navigated = False

    def _on_navigated(frame) -> None:
        nonlocal navigated
        if frame == page.main_frame:
            navigated = True

    page.on("framenavigated", _on_navigated)
    try:
        await card_locator.click(timeout=timeout_ms)
        # Yield briefly so the framenavigated event can fire before we check.
        await page.wait_for_timeout(150)
        if navigated:
            # Click caused a page reload instead of opening a modal -- the site's
            # frontend changed. Wait for the reload to settle so the page is usable
            # again, then bail out. Caller's circuit breaker will stop further attempts.
            logger.warning(
                "Card click triggered page navigation instead of opening modal "
                "(site frontend change?) -- skipping location lookup"
            )
            await _capture_failure_diagnostics(page, "navigation", item_name, seller_name, shop_name)
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass
            return None
        await page.wait_for_selector(MODAL_WRAP, timeout=timeout_ms)
        await page.wait_for_timeout(300)  # let modal content finish rendering
        raw = await page.evaluate(_EXTRACT_MODAL_JS)
    except Exception as exc:
        logger.warning("Failed to open/read location modal: %s", exc)
        await _capture_failure_diagnostics(page, "exception", item_name, seller_name, shop_name)
        await _force_close_any_overlay(page)
        return None
    finally:
        try:
            page.remove_listener("framenavigated", _on_navigated)
        except Exception:
            pass
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
        except Exception:
            pass

    location_field = raw.get("Localização da loja")
    seller_field = raw.get("Nome do Vendedor")
    server_field = raw.get("Informações do tipo")

    map_name = location_field["value"] if location_field else None
    x_pos, y_pos = _parse_coords(location_field["coords"] if location_field else None)
    seller_name = seller_field["value"] if seller_field else None
    server_name = server_field["value"] if server_field else None
    item_name_title = raw.get("itemNameTitle")

    return ShopLocationDetail(
        map_name=map_name, x_pos=x_pos, y_pos=y_pos, seller_name=seller_name, server_name=server_name,
        item_name_title=item_name_title,
    )
