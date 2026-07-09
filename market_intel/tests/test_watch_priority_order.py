from db.repository import add_tracked_item, add_watch_rule, list_tracked_items, list_watched_item_names


def test_watched_items_sort_first_preserving_registration_order(session):
    a = add_tracked_item(session, item_name="Elunium")
    b = add_tracked_item(session, item_name="Oridecon")
    c = add_tracked_item(session, item_name="Steel")
    d = add_tracked_item(session, item_name="Coal")
    session.commit()

    add_watch_rule(session, raw="Steel > 100", item_name="Steel", operator=">", target_price=100)
    add_watch_rule(session, raw="Coal > 100", item_name="Coal", operator=">", target_price=100)
    session.commit()

    items = list_tracked_items(session, active_only=True)
    watched = list_watched_item_names(session)
    items.sort(key=lambda it: it.item_name not in watched)

    assert [i.item_name for i in items] == ["Steel", "Coal", "Elunium", "Oridecon"]
