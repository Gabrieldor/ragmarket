"""
One-time recovery script for the backwards-continuation bug introduced in the
"fix: prevent expired shop qty from being counted as sold on new orders" commit.

What went wrong:
  Sessions that were in the buggy state (status="active", ended_reason="shop_removed") had
  their SSI reversed to an old value and were wrongly closed as "sold_out_early" on the
  first sync after that commit. The actual current listing's SSI was consumed/skipped.

Run from repo root:
  cd /home/ubuntu/Rag
  .venv/bin/python -m market_intel.scripts.fix_backwards_continuation [--fix]

Without --fix, prints a dry-run report. Add --fix to apply changes.
"""

import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/home/ubuntu/Rag")

from sqlalchemy import select, text

from market_intel.db.models import MyListingSession, MySaleEvent
from market_intel.db.session import SessionLocal


def main():
    fix = "--fix" in sys.argv

    db = SessionLocal()
    try:
        # Find sessions that might have been corrupted:
        # status="sold_out_early", ended_reason=NULL, dismissed=False, and no MySaleEvent rows
        # (because the "sale" was fictional -- the qty was just the old listing's remaining qty).
        sessions = list(db.scalars(
            select(MyListingSession).where(
                MyListingSession.status == "sold_out_early",
                MyListingSession.ended_reason.is_(None),
                MyListingSession.dismissed.is_(False),
            )
        ))

        print(f"Found {len(sessions)} sold_out_early sessions with ended_reason=NULL:")
        print()

        candidates = []
        for s in sessions:
            # Check if this session has any MySaleEvent rows
            sale_count = db.scalar(
                select(MySaleEvent.id).where(MySaleEvent.session_id == s.id).limit(1)
            )
            has_sales = sale_count is not None

            print(
                f"  id={s.id:5d} ssi={s.ssi!r:20s} seller={s.seller_name!r:15s} "
                f"window_start={s.window_start} qty_sold={s.total_quantity_sold:4d} "
                f"has_sale_events={'yes' if has_sales else 'NO'}"
            )

            # Suspicious if it has no sale events but total_quantity_sold > 0
            if not has_sales and s.total_quantity_sold > 0:
                candidates.append(s)

        print()
        print(f"Suspicious (sold qty claimed but no sale events): {len(candidates)}")
        for s in candidates:
            print(f"  -> id={s.id} ssi={s.ssi!r} qty_sold={s.total_quantity_sold}")

        if not candidates:
            print("\nNothing to fix.")
            return

        if not fix:
            print("\nDry run -- re-run with --fix to dismiss these sessions.")
            print("Dismissing lets the collector re-create them correctly on next cycle.")
            return

        print("\nDismissing suspicious sessions...")
        for s in candidates:
            s.dismissed = True
            s.dismissed_at = datetime.utcnow()
            print(f"  Dismissed id={s.id} ssi={s.ssi!r}")

        db.commit()
        print("Done. The collector will create fresh sessions for current listings on next cycle.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
