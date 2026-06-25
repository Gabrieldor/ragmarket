"""Watch-rule string parsing, ported from D:\\Rag\\src\\parser.py's parse_rule/
_parse_price_input -- kept as plain functions (no dataclass) since the parsed fields are
stored directly on the db.models.WatchRule row instead of a separate value object.
"""

import re


def _parse_price_input(price_str: str) -> int:
    """Convert a user-supplied price string to an integer.

    Supports plain numbers as well as K/KK suffixes (case-insensitive):
      ``25k``   -> 25 000
      ``25kk``  -> 25 000 000
      ``25000`` -> 25 000
    """
    price_str = price_str.strip()
    match = re.match(r'^(\d+(?:[.,]\d+)?)\s*(kk|k)?$', price_str, re.IGNORECASE)
    if not match:
        raise ValueError(f"Cannot parse price: {price_str!r}")
    number = float(match.group(1).replace(',', '.'))
    suffix = (match.group(2) or '').lower()
    if suffix == 'kk':
        number *= 1_000_000
    elif suffix == 'k':
        number *= 1_000
    return int(number)


def parse_rule(rule_str: str) -> tuple[str, str, int]:
    """Parse a rule string such as ``'Elunium > 25k'`` into ``(item_name, operator,
    target_price)``.

    Only ``>`` and ``<`` are accepted as operators. Internally they are treated as ``>=``
    and ``<=`` (plus optional variance, see notifications.checker) to avoid missing edge
    cases.

    Price supports K and KK suffixes:
      ``25k`` -> 25 000   ``25kk`` -> 25 000 000

    Raises:
        ValueError: When the format is invalid.
    """
    rule_str = rule_str.strip()
    match = re.match(r'^(.+?)\s*([><])\s*(\d+(?:[.,]\d+)?\s*(?:kk|k)?)\s*$', rule_str, re.IGNORECASE)
    if not match:
        raise ValueError(
            f"Invalid rule format: {rule_str!r}. "
            "Expected: '<Item Name> > <Price>'  or  '<Item Name> < <Price>'\n"
            "Price examples: 30000  25k  25kk"
        )
    item_name = match.group(1).strip()
    operator = match.group(2)
    target_price = _parse_price_input(match.group(3))
    return item_name, operator, target_price
