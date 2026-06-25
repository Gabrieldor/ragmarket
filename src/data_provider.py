from abc import ABC, abstractmethod
from typing import NamedTuple


class Listing(NamedTuple):
    price: int
    quantity: int


class DataProvider(ABC):
    """Abstract interface for price data sources.

    Switching between Playwright and HTTP requires only changing which
    concrete class is instantiated in main.py — all monitoring logic
    works against this interface.
    """

    @abstractmethod
    async def setup(self) -> None:
        """Initialize the provider (browser launch, session creation, etc.)."""

    @abstractmethod
    async def teardown(self) -> None:
        """Release all resources held by the provider."""

    @abstractmethod
    async def get_listings(
        self,
        item_name: str,
        store_type: str = "BUY",
        server_type: str = "FREYA",
        sort: str = "RELATED",
        max_pages: int = 1,
    ) -> list[Listing]:
        """Return all listings for *item_name* as (price, quantity) pairs.

        Args:
            item_name:   Exact item name as shown on the catalog (e.g. ``"Elunium"``).
            store_type:  ``"BUY"`` or ``"SELL"``.
            server_type: Server name (e.g. ``"FREYA"``).
            sort:        ``"RELATED"``, ``"HIGH_PRICE"``, or ``"LOW_PRICE"``.
            max_pages:   How many result pages to scrape.

        Returns:
            List of :class:`Listing` named tuples.  Empty list when no results found.
        """
