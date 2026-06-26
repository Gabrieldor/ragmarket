from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.schemas import CollectorConfigOut, CollectorConfigUpdate, CollectorStatusOut
from db.repository import (
    get_collector_config,
    get_collector_status,
    set_collector_paused,
    set_collector_retry,
    update_collector_config,
)
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
            next_item_at=None, consecutive_rate_limits=0, paused=False, updated_at=None,
        )

    now = datetime.now()
    if status.paused:
        # A paused collector writes "paused" state continuously, so staleness
        # doesn't apply — it's intentionally not making progress.
        effective_state = "paused"
        is_stale = False
    elif status.state in ("sleeping", "rate_limited") and status.next_cycle_at is not None:
        is_stale = now > status.next_cycle_at + timedelta(seconds=SLEEP_GRACE_SECONDS)
        effective_state = status.state
    else:
        is_stale = now - status.updated_at > timedelta(seconds=SCRAPING_STALE_AFTER_SECONDS)
        effective_state = status.state

    return CollectorStatusOut(
        state="offline" if is_stale else effective_state,
        current_item_name=status.current_item_name,
        next_cycle_at=status.next_cycle_at,
        next_item_at=status.next_item_at,
        consecutive_rate_limits=status.consecutive_rate_limits,
        paused=status.paused,
        updated_at=status.updated_at,
    )


@router.post("/pause", response_model=CollectorStatusOut)
def pause_collector(db: Session = Depends(get_db)):
    set_collector_paused(db, paused=True)
    db.commit()
    return collector_status(db)


@router.post("/resume", response_model=CollectorStatusOut)
def resume_collector(db: Session = Depends(get_db)):
    set_collector_paused(db, paused=False)
    db.commit()
    return collector_status(db)


@router.post("/retry", response_model=CollectorStatusOut)
def retry_collector(db: Session = Depends(get_db)):
    """Signal the collector to abandon its current backoff sleep and retry immediately.
    Only meaningful when the collector is in the rate_limited state.
    """
    set_collector_retry(db)
    db.commit()
    return collector_status(db)


@router.get("/config", response_model=CollectorConfigOut)
def get_config(db: Session = Depends(get_db)):
    return get_collector_config(db)


@router.patch("/config", response_model=CollectorConfigOut)
def update_config(body: CollectorConfigUpdate, db: Session = Depends(get_db)):
    cfg = update_collector_config(
        db,
        poll_interval_seconds=body.poll_interval_seconds,
        item_delay_seconds=body.item_delay_seconds,
        location_click_delay_seconds=body.location_click_delay_seconds,
    )
    db.commit()
    return cfg
