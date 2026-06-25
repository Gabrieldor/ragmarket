import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class WatchRule:
    raw: str
    item_name: str
    operator: str   # '>' or '<'
    target_price: int

    def __str__(self) -> str:
        return self.raw


def _parse_price_input(price_str: str) -> int:
    """Convert a user-supplied price string to an integer.

    Supports plain numbers as well as K/KK suffixes (case-insensitive):
      ``25k``   → 25 000
      ``25kk``  → 25 000 000
      ``25000`` → 25 000
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


def parse_rule(rule_str: str) -> WatchRule:
    """Parse a rule string such as ``'Elunium > 25k'`` into a :class:`WatchRule`.

    Only ``>`` and ``<`` are accepted as operators.  Internally they are treated
    as ``>=`` and ``<=`` (plus optional variance) to avoid missing edge cases.

    Price supports K and KK suffixes:
      ``25k`` → 25 000   ``25kk`` → 25 000 000

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
    return WatchRule(raw=rule_str, item_name=item_name, operator=operator, target_price=target_price)


def parse_price_text(text: str) -> Optional[int]:
    """Convert a price string from the catalog into an integer.

    The site uses Portuguese number formatting where dots are thousands
    separators (``"26.999"`` → ``26999``).  All non-digit characters are
    stripped so the function is tolerant of minor HTML variations.
    """
    digits = re.sub(r'[^\d]', '', text.strip())
    return int(digits) if digits else None
