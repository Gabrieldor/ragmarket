"""Watch-rule string parsing, ported from D:\\Rag\\src\\parser.py's parse_rule/
_parse_price_input -- kept as plain functions (no dataclass) since the parsed fields are
stored directly on the db.models.WatchRule row instead of a separate value object.
"""

import re

# Leading refine prefix, e.g. "+7 Sapatos do Lobo Cinzento" -> refine level 7.
# Shared with scraper_adapter.location_action (imported there, not duplicated).
REFINE_PREFIX_RE = re.compile(r'^\+(\d+)\s*')

# Trailing slot-count suffix, e.g. "Item Name [1]" -> slot count 1.
# Shared with scraper_adapter.location_action (imported there, not duplicated).
SLOT_SUFFIX_RE = re.compile(r'\s*\[(\d+)\]\s*$')

# Map-name token, e.g. "Item @wolfvill" -> map name "wolfvill". Can appear anywhere in the
# free-text portion of the rule (not just leading/trailing), so this is searched for, not
# anchored.
MAP_TOKEN_RE = re.compile(r'@(\S+)')

# Excluded-map token, e.g. "Item !auction_02" -> excludes map "auction_02". Can appear
# multiple times (e.g. "Item !auction_02 !prt_fild08"), collected into excluded_maps.
EXCLUDE_MAP_TOKEN_RE = re.compile(r'!(\S+)')

# Minimum-quantity token, e.g. "Item #200" -> required_min_qty=200. At most one per rule.
QTY_TOKEN_RE = re.compile(r'#(\d+)')


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


def parse_rule(
    rule_str: str,
) -> tuple[str, str, int, int | None, int | None, str | None, str | None, int | None]:
    """Parse a rule string such as ``'Elunium > 25k'`` into ``(item_name, operator,
    target_price, required_refine, required_slot, required_map, excluded_maps,
    required_min_qty)``.

    Only ``>`` and ``<`` are accepted as operators. Internally they are treated as ``>=``
    and ``<=`` (plus optional variance, see notifications.checker) to avoid missing edge
    cases.

    Price supports K and KK suffixes:
      ``25k`` -> 25 000   ``25kk`` -> 25 000 000

    The raw item name may also carry a leading refine prefix (``+7 ...``), a trailing
    slot-count suffix (``... [1]``), one or more excluded-map tokens (``!mapname``), an
    ``@mapname`` token, and/or a ``#qty`` token, each appearing anywhere in the free-text
    portion, e.g.::

        '+7 Sapatos do Lobo Cinzento [1] < 25kk'
        -> item_name='Sapatos do Lobo Cinzento', operator='<', target_price=25_000_000,
           required_refine=7, required_slot=1, required_map=None, excluded_maps=None,
           required_min_qty=None

        'Item @wolfvill > 30k'
        -> item_name='Item', operator='>', target_price=30_000, required_map='wolfvill'

        'Item !auction_02 !prt_fild08 #200 < 25kk'
        -> item_name='Item', operator='<', target_price=25_000_000,
           excluded_maps='auction_02,prt_fild08', required_min_qty=200

    All tokens are optional and independent; a rule with none yields
    ``required_refine=None, required_slot=None, required_map=None, excluded_maps=None,
    required_min_qty=None`` and behaves exactly as before.

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

    required_refine: int | None = None
    refine_match = REFINE_PREFIX_RE.match(item_name)
    if refine_match:
        required_refine = int(refine_match.group(1))
        item_name = item_name[refine_match.end():].strip()

    excluded_maps: str | None = None
    exclude_matches = list(EXCLUDE_MAP_TOKEN_RE.finditer(item_name))
    if exclude_matches:
        excluded_maps = ",".join(m.group(1).lower() for m in exclude_matches)
        item_name = EXCLUDE_MAP_TOKEN_RE.sub("", item_name).strip()
        item_name = re.sub(r'\s{2,}', ' ', item_name)

    required_map: str | None = None
    map_match = MAP_TOKEN_RE.search(item_name)
    if map_match:
        required_map = map_match.group(1).lower()
        item_name = (item_name[:map_match.start()] + item_name[map_match.end():]).strip()
        item_name = re.sub(r'\s{2,}', ' ', item_name)

    required_min_qty: int | None = None
    qty_match = QTY_TOKEN_RE.search(item_name)
    if qty_match:
        required_min_qty = int(qty_match.group(1))
        item_name = (item_name[:qty_match.start()] + item_name[qty_match.end():]).strip()
        item_name = re.sub(r'\s{2,}', ' ', item_name)

    # Slot suffix must be checked last: it's end-anchored, and the @/!/# tokens above may
    # have followed it in the original string (e.g. "Item [1] @map !ex #200"), so it only
    # becomes the true trailing suffix once those tokens are stripped out.
    required_slot: int | None = None
    slot_match = SLOT_SUFFIX_RE.search(item_name)
    if slot_match:
        required_slot = int(slot_match.group(1))
        item_name = item_name[:slot_match.start()].strip()

    return (
        item_name, operator, target_price, required_refine, required_slot,
        required_map, excluded_maps, required_min_qty,
    )
