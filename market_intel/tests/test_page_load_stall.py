import asyncio

import pytest

from scraper_adapter.provider_adapter import DetailedListingProvider, PageLoadStallError


class _FakeLocator:
    def __init__(self, count: int):
        self._count = count

    async def count(self):
        return self._count


class _FakeSpinnerLocator:
    async def count(self):
        return 0


class _FakePage:
    """Minimal stand-in for a Playwright Page: content never appears (neither item cards
    nor the no-results UI), simulating a page that failed to load entirely (e.g. under
    sustained 429 throttling).
    """

    def __init__(self, *, cards_appear_on_attempt: int | None = None):
        self.cards_appear_on_attempt = cards_appear_on_attempt
        self.wait_for_selector_calls = 0
        self.reload_calls = 0

    async def goto(self, *a, **kw):
        class _Resp:
            status = 200
        return _Resp()

    def locator(self, selector):
        if selector == "img[src*='loading-gif']":
            return _FakeSpinnerLocator()
        if "data-id" in selector:
            appeared = (
                self.cards_appear_on_attempt is not None
                and self.reload_calls + 1 >= self.cards_appear_on_attempt
            )
            return _FakeLocator(1 if appeared else 0)
        return _FakeLocator(0)

    async def wait_for_selector(self, *a, **kw):
        self.wait_for_selector_calls += 1
        raise TimeoutError("simulated: content never attached")

    async def wait_for_load_state(self, *a, **kw):
        return None

    async def reload(self, *a, **kw):
        self.reload_calls += 1

    async def evaluate(self, *a, **kw):
        return []

    async def wait_for_function(self, *a, **kw):
        return True  # CSS "ready" -- keeps the unrelated CSS-ready-reload path out of these tests


def test_page_load_stall_raises_after_retries_exhausted():
    provider = DetailedListingProvider(headless=True)
    page = _FakePage(cards_appear_on_attempt=None)  # never appears

    async def run():
        await provider._scrape_page(page, "Elunium", "BUY", "FREYA", "LOW_PRICE", 1)

    with pytest.raises(PageLoadStallError):
        asyncio.run(run())

    assert page.reload_calls == 2  # 3 attempts total: 2 reloads between them


def test_page_load_stall_recovers_if_cards_appear_on_retry():
    provider = DetailedListingProvider(headless=True)
    page = _FakePage(cards_appear_on_attempt=2)  # shows up on the 2nd attempt

    listings = asyncio.run(
        provider._scrape_page(page, "Elunium", "BUY", "FREYA", "LOW_PRICE", 1)
    )

    assert listings == []  # evaluate() stub returns no rows, but no exception raised
    assert page.reload_calls == 1
