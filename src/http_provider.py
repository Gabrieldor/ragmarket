"""HTTP-based provider — NOT ACTIVE.

The target site (ro.gnjoylatam.com) renders item listings server-side via
Next.js, so the raw HTML response does contain price data.  However, the site
applies browser-fingerprinting checks and cookie-gating that make plain HTTP
requests unreliable in practice.

This stub satisfies the provider interface so the abstraction layer is
complete.  To activate it, replace ``PlaywrightProvider`` with
``HttpProvider`` in ``main.py`` and install the extra dependencies:

    pip install httpx beautifulsoup4

Selected method: Playwright (headless Chrome)
Reason: Guaranteed JS execution and full browser environment bypass any
        fingerprinting or lazy-loading that would break plain HTTP requests.
"""

from data_provider import DataProvider, Listing


class HttpProvider(DataProvider):
    async def setup(self) -> None:
        raise NotImplementedError(
            "HttpProvider is not active.  Use PlaywrightProvider instead."
        )

    async def teardown(self) -> None:
        raise NotImplementedError(
            "HttpProvider is not active.  Use PlaywrightProvider instead."
        )

    async def get_listings(
        self,
        item_name: str,
        store_type: str = "BUY",
        server_type: str = "FREYA",
        sort: str = "RELATED",
        max_pages: int = 1,
    ) -> list[Listing]:
        raise NotImplementedError(
            "HttpProvider is not active.  Use PlaywrightProvider instead."
        )
