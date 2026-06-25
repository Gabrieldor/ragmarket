from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas import CollectorStatusOut
from db.repository import get_collector_status
from db.session import get_db
from settings import settings

router = APIRouter(prefix="/collector", tags=["collector"])

# While actively scraping, updates land roughly every item -- a short gap means dead/stuck.
SCRAPING_STALE_AFTER_SECONDS = max(120, settings.poll_interval_seconds + 60)
# While sleeping/rate_limited, no update is expected until next_cycle_at arrives -- that can be
# hours away for an escalated rate-limit backoff, so staleness must be judged against
# next_cycle_at (plus a grace period for the cycle to actually start), not a fixed short window.
SLEEP_GRACE_SECONDS = 180


@router.get("/status", response_model=CollectorStatusOut)
def collector_status(db: Session = Depends(get_db)):
    status = get_collector_status(db)
    if status is None:
        return CollectorStatusOut(
            state="offline", current_item_name=None, next_cycle_at=None,
            consecutive_rate_limits=0, updated_at=None,
        )

    now = datetime.now()
    if status.state in ("sleeping", "rate_limited") and status.next_cycle_at is not None:
        is_stale = now > status.next_cycle_at + timedelta(seconds=SLEEP_GRACE_SECONDS)
    else:
        is_stale = now - status.updated_at > timedelta(seconds=SCRAPING_STALE_AFTER_SECONDS)

    return CollectorStatusOut(
        state="offline" if is_stale else status.state,
        current_item_name=status.current_item_name,
        next_cycle_at=status.next_cycle_at,
        consecutive_rate_limits=status.consecutive_rate_limits,
        updated_at=status.updated_at,
    )
