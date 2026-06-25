import asyncio
from dataclasses import dataclass

from db.models import NotificationEvent, NotificationSettings, WatchRule
from notifications.checker import check_watch_rules, evaluate_rule


@dataclass
class _Listing:
    price: int
    quantity: int


class _Rule:
    """Lightweight WatchRule stand-in -- evaluate_rule only reads these attributes."""

    def __init__(self, raw, item_name, operator, target_price):
        self.raw = raw
        self.item_name = item_name
        self.operator = operator
        self.target_price = target_price


# ── evaluate_rule ───────────────────────────────────────────────────────────────

def test_less_than_true_when_cheapest_at_or_below_bound():
    rule = _Rule("Elunium < 1000", "Elunium", "<", 1000)
    met, price = evaluate_rule(rule, [_Listing(900, 5)], variance_percent=0, min_items_below=0)
    assert met is True
    assert price == 900


def test_less_than_false_when_cheapest_above_bound():
    rule = _Rule("Elunium < 1000", "Elunium", "<", 1000)
    met, price = evaluate_rule(rule, [_Listing(1200, 5)], variance_percent=0, min_items_below=0)
    assert met is False
    assert price == 1200  # the real cheapest price is still reported even when not met


def test_greater_than_default_true_when_cheapest_at_or_above_bound():
    rule = _Rule("Elunium > 1000", "Elunium", ">", 1000)
    met, price = evaluate_rule(rule, [_Listing(1100, 5)], variance_percent=0, min_items_below=0)
    assert met is True
    assert price == 1100


def test_greater_than_supply_mode_true_when_supply_below_threshold():
    rule = _Rule("Elunium > 1000", "Elunium", ">", 1000)
    # Only 30 total quantity priced below 1000 -- below the 50 threshold -> supply low -> met.
    listings = [_Listing(900, 20), _Listing(950, 10), _Listing(1200, 100)]
    met, price = evaluate_rule(rule, listings, variance_percent=0, min_items_below=50)
    assert met is True
    assert price == 900  # cheapest reported regardless of operator


def test_greater_than_supply_mode_false_when_supply_above_threshold():
    rule = _Rule("Elunium > 1000", "Elunium", ">", 1000)
    listings = [_Listing(900, 100), _Listing(1200, 100)]
    met, _ = evaluate_rule(rule, listings, variance_percent=0, min_items_below=50)
    assert met is False


def test_variance_widens_bounds():
    rule = _Rule("Elunium < 1000", "Elunium", "<", 1000)
    # 1050 is above the raw bound but within 10% variance (upper bound 1100).
    met, price = evaluate_rule(rule, [_Listing(1050, 5)], variance_percent=10, min_items_below=0)
    assert met is True
    assert price == 1050


def test_no_listings_never_matches():
    rule = _Rule("Elunium < 1000", "Elunium", "<", 1000)
    assert evaluate_rule(rule, [], variance_percent=0, min_items_below=0) == (False, None)


# ── check_watch_rules state machine ─────────────────────────────────────────────

class _FakeProvider:
    def __init__(self, listings_by_item):
        self.listings_by_item = listings_by_item
        self.calls = []

    async def get_listings(self, item_name, store_type, server_type, sort, max_pages):
        self.calls.append(item_name)
        return self.listings_by_item.get(item_name, [])


class _FakeNotifier:
    def __init__(self):
        self.sent = []

    async def send_triggered(self, rule, price):
        self.sent.append(("triggered", rule.raw, price, None))

    async def send_cleared(self, rule):
        self.sent.append(("cleared", rule.raw, None, None))

    async def send_price_changed(self, rule, old_price, new_price):
        self.sent.append(("price_changed", rule.raw, new_price, old_price))


def _config(**overrides) -> NotificationSettings:
    defaults = dict(
        local_sound=True, variance_percent=0.0, min_items_below=0,
        rule_delay_seconds=0.0, store_type="BUY", server_type="FREYA", max_pages=1,
        user_mention="",
    )
    defaults.update(overrides)
    return NotificationSettings(**defaults)


def test_check_watch_rules_fires_triggered_on_first_match(session):
    rule = WatchRule(raw="Elunium > 1000", item_name="Elunium", operator=">", target_price=1000)
    session.add(rule)
    session.commit()

    provider = _FakeProvider({"Elunium": [_Listing(1100, 5)]})
    notifier = _FakeNotifier()
    fired = asyncio.run(check_watch_rules(session, provider, notifier, _config()))
    session.commit()

    assert fired == 1
    assert notifier.sent == [("triggered", "Elunium > 1000", 1100, None)]
    assert rule.state_active is True
    assert rule.last_price == 1100
    assert session.query(NotificationEvent).filter_by(watch_rule_id=rule.id).count() == 1


def test_check_watch_rules_persists_current_price_even_when_condition_not_met(session):
    """Regression test: the dashboard's "current price" column must update every check,
    not just when a notification fires -- otherwise a rule that never triggers shows '-'
    forever even though it's being checked correctly.
    """
    rule = WatchRule(raw="Elunium > 1000", item_name="Elunium", operator=">", target_price=1000)
    session.add(rule)
    session.commit()

    provider = _FakeProvider({"Elunium": [_Listing(500, 5)]})  # well below the bound -- not met
    notifier = _FakeNotifier()
    fired = asyncio.run(check_watch_rules(session, provider, notifier, _config()))

    assert fired == 0
    assert rule.state_active is False
    assert rule.last_checked_price == 500
    assert rule.last_checked_at is not None


def test_check_watch_rules_silent_while_condition_holds_steady(session):
    rule = WatchRule(
        raw="Elunium > 1000", item_name="Elunium", operator=">", target_price=1000,
        state_active=True, last_price=1100,
    )
    session.add(rule)
    session.commit()

    provider = _FakeProvider({"Elunium": [_Listing(1100, 5)]})  # unchanged price
    notifier = _FakeNotifier()
    fired = asyncio.run(check_watch_rules(session, provider, notifier, _config()))

    assert fired == 0
    assert notifier.sent == []


def test_check_watch_rules_fires_cleared_when_condition_no_longer_met(session):
    rule = WatchRule(
        raw="Elunium > 1000", item_name="Elunium", operator=">", target_price=1000,
        state_active=True, last_price=1100,
    )
    session.add(rule)
    session.commit()

    provider = _FakeProvider({"Elunium": [_Listing(500, 5)]})  # now below the bound
    notifier = _FakeNotifier()
    fired = asyncio.run(check_watch_rules(session, provider, notifier, _config()))
    session.commit()

    assert fired == 1
    assert notifier.sent == [("cleared", "Elunium > 1000", None, None)]
    assert rule.state_active is False
    assert rule.last_price is None


def test_check_watch_rules_fires_price_changed_while_still_active(session):
    rule = WatchRule(
        raw="Elunium > 1000", item_name="Elunium", operator=">", target_price=1000,
        state_active=True, last_price=1100,
    )
    session.add(rule)
    session.commit()

    provider = _FakeProvider({"Elunium": [_Listing(1300, 5)]})
    notifier = _FakeNotifier()
    fired = asyncio.run(check_watch_rules(session, provider, notifier, _config()))

    assert fired == 1
    assert notifier.sent == [("price_changed", "Elunium > 1000", 1300, 1100)]
    assert rule.last_price == 1300


def test_check_watch_rules_skips_inactive_rules(session):
    rule = WatchRule(
        raw="Elunium > 1000", item_name="Elunium", operator=">", target_price=1000, is_active=False,
    )
    session.add(rule)
    session.commit()

    provider = _FakeProvider({"Elunium": [_Listing(1100, 5)]})
    notifier = _FakeNotifier()
    fired = asyncio.run(check_watch_rules(session, provider, notifier, _config()))

    assert fired == 0
    assert provider.calls == []
