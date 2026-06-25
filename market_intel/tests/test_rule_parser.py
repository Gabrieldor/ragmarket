import pytest

from notifications.rule_parser import parse_rule


def test_parse_plain_number():
    item_name, operator, target_price = parse_rule("Elunium > 30000")
    assert item_name == "Elunium"
    assert operator == ">"
    assert target_price == 30000


def test_parse_k_suffix():
    item_name, operator, target_price = parse_rule("Elunium > 30k")
    assert target_price == 30_000


def test_parse_kk_suffix():
    item_name, operator, target_price = parse_rule("Oridecon < 5kk")
    assert target_price == 5_000_000


def test_parse_item_name_with_spaces():
    item_name, _, _ = parse_rule("Tiara Carnavalesca < 20kk")
    assert item_name == "Tiara Carnavalesca"


def test_parse_decimal_price():
    _, _, target_price = parse_rule("Elunium > 1.5k")
    assert target_price == 1500


@pytest.mark.parametrize("bad_rule", [
    "Elunium",
    "Elunium == 100",
    "Elunium > ",
    "> 100",
])
def test_invalid_rule_raises(bad_rule):
    with pytest.raises(ValueError):
        parse_rule(bad_rule)
