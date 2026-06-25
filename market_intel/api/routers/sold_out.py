from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.schemas import SoldOutConfigOut, SoldOutConfigUpdate, SoldOutEventOut, SoldOutSummaryOut
from db.repository import get_active_sold_out_counts, get_sold_out_config, list_sold_out_events, update_sold_out_config
from db.session import get_db

router = APIRouter(prefix="/sold-out", tags=["sold-out"])


@router.get("/config", response_model=SoldOutConfigOut)
def get_config(db: Session = Depends(get_db)):
    config = get_sold_out_config(db)
    db.commit()
    return config


@router.patch("/config", response_model=SoldOutConfigOut)
def patch_config(payload: SoldOutConfigUpdate, db: Session = Depends(get_db)):
    config = update_sold_out_config(
        db,
        threshold_ratio=payload.threshold_ratio,
        quiet_hours_start=payload.quiet_hours_start,
        quiet_hours_end=payload.quiet_hours_end,
        clear_quiet_hours=payload.clear_quiet_hours,
    )
    db.commit()
    return config


@router.get("/events", response_model=list[SoldOutEventOut])
def get_events(
    tracked_item_id: int | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return list_sold_out_events(db, tracked_item_id=tracked_item_id, limit=limit, offset=offset)


@router.get("/summary", response_model=list[SoldOutSummaryOut])
def get_summary(db: Session = Depends(get_db)):
    counts = get_active_sold_out_counts(db)
    return [
        SoldOutSummaryOut(tracked_item_id=tracked_item_id, active_count=count)
        for tracked_item_id, count in counts.items()
    ]
