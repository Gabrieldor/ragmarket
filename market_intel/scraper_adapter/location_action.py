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

from playwright.async_api import Page

logger = logging.getLogger(__name__)

# Selectors isolated here, mirroring the SELECTORS block convention in
# playwright_provider.py -- edit only this block if the site's modal markup changes.
MODAL_INFO_ITEM = '[class*="style_shop_info__"]'
MODAL_WRAP = '[class*="style_shop_info_content_wrap"]'

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
    return result;
}
"""


class ShopLocationDetail:
    def __init__(self, map_name: str | None, x_pos: int | None, y_pos: int | None, seller_name: str | None, server_name: str | None):
        self.map_name = map_name
        self.x_pos = x_pos
        self.y_pos = y_pos
        self.seller_name = seller_name
        self.server_name = server_name


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


async def fetch_shop_location(page: Page, card_locator, timeout_ms: int = 8_000) -> ShopLocationDetail | None:
    """Click a single result card and read its location modal.

    ``card_locator`` is a Playwright Locator pointing at exactly one ``li[data-id]``
    element on the currently-loaded results page. Closes the modal before
    returning, leaving the page ready for the next card. ``timeout_ms`` is
    deliberately short (modals render in ~1s under normal conditions per live
    testing) so a stuck attempt fails fast rather than blocking for the full
    page-navigation timeout.
    """
    try:
        await card_locator.click(timeout=timeout_ms)
        await page.wait_for_selector(MODAL_WRAP, timeout=timeout_ms)
        await page.wait_for_timeout(300)  # let modal content finish rendering
        raw = await page.evaluate(_EXTRACT_MODAL_JS)
    except Exception as exc:
        logger.warning("Failed to open/read location modal: %s", exc)
        await _force_close_any_overlay(page)
        return None
    finally:
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

    return ShopLocationDetail(
        map_name=map_name, x_pos=x_pos, y_pos=y_pos, seller_name=seller_name, server_name=server_name
    )
