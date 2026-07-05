import pytest

from notifications.rule_parser import parse_rule


def test_parse_plain_number():
    item_name, operator, target_price, required_refine, required_slot, required_map = parse_rule("Elunium > 30000")
    assert item_name == "Elunium"
    assert operator == ">"
    assert target_price == 30000
    assert required_refine is None
    assert required_slot is None
    assert required_map is None


def test_parse_k_suffix():
    item_name, operator, target_price, required_refine, required_slot, required_map = parse_rule("Elunium > 30k")
    assert target_price == 30_000
    assert required_refine is None
    assert required_slot is None
    assert required_map is None


def test_parse_kk_suffix():
    item_name, operator, target_price, required_refine, required_slot, required_map = parse_rule("Oridecon < 5kk")
    assert target_price == 5_000_000
    assert required_refine is None
    assert required_slot is None
    assert required_map is None


def test_parse_item_name_with_spaces():
    item_name, _, _, required_refine, required_slot, required_map = parse_rule("Tiara Carnavalesca < 20kk")
    assert item_name == "Tiara Carnavalesca"
    assert required_refine is None
    assert required_slot is None
    assert required_map is None


def test_parse_decimal_price():
    _, _, target_price, required_refine, required_slot, required_map = parse_rule("Elunium > 1.5k")
    assert target_price == 1500
    assert required_refine is None
    assert required_slot is None
    assert required_map is None


def test_parse_map_token():
    item_name, operator, target_price, required_refine, required_slot, required_map = parse_rule(
        "Item @wolfvill > 30k"
    )
    assert item_name == "Item"
    assert operator == ">"
    assert target_price == 30_000
    assert required_refine is None
    assert required_slot is None
    assert required_map == "wolfvill"


def test_parse_map_token_leading():
    item_name, operator, target_price, required_refine, required_slot, required_map = parse_rule(
        "@wolfvill Item > 30k"
    )
    assert item_name == "Item"
    assert required_map == "wolfvill"


def test_parse_refine_slot_map_combined():
    item_name, operator, target_price, required_refine, required_slot, required_map = parse_rule(
        "+7 Item @wolfvill [1] < 25kk"
    )
    assert item_name == "Item"
    assert operator == "<"
    assert target_price == 25_000_000
    assert required_refine == 7
    assert required_slot == 1
    assert required_map == "wolfvill"


@pytest.mark.parametrize("bad_rule", [
    "Elunium",
    "Elunium == 100",
    "Elunium > ",
    "> 100",
])
def test_invalid_rule_raises(bad_rule):
    with pytest.raises(ValueError):
        parse_rule(bad_rule)
