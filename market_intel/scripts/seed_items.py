"""Bulk-add tracked items from a simple text list, one item name per line.

Usage (from market_intel/, with the venv active):
    python scripts/seed_items.py items.txt
"""

import sys
from pathlib import Path

MARKET_INTEL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MARKET_INTEL_DIR))

from db.repository import add_tracked_item, list_tracked_items  # noqa: E402
from db.session import get_session  # noqa: E402
from settings import settings  # noqa: E402


def main(list_path: str) -> None:
    names = [
        line.strip()
        for line in Path(list_path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    with get_session() as session:
        existing_names = {item.item_name for item in list_tracked_items(session)}
        added = 0
        for name in names:
            if name in existing_names:
                print(f"Skipping (already tracked): {name}")
                continue
            add_tracked_item(
                session,
                item_name=name,
                server_name=settings.server_type,
                store_type=settings.store_type,
            )
            added += 1
            print(f"Added: {name}")

    print(f"\nDone. {added} item(s) added.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/seed_items.py <path-to-item-list.txt>")
        sys.exit(1)
    main(sys.argv[1])
