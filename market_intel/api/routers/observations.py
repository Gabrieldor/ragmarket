from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import ObservationOut
from db.models import ListingObservation
from db.session import get_db

router = APIRouter(prefix="/observations", tags=["observations"])


@router.get("", response_model=list[ObservationOut])
def get_observations(
    tracked_item_id: int | None = None,
    seller_name: str | None = None,
    shop_name: str | None = None,
    map_name: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    stmt = select(ListingObservation)
    if tracked_item_id is not None:
        stmt = stmt.where(ListingObservation.tracked_item_id == tracked_item_id)
    if seller_name:
        stmt = stmt.where(ListingObservation.seller_name.ilike(f"%{seller_name}%"))
    if shop_name:
        stmt = stmt.where(ListingObservation.shop_name.ilike(f"%{shop_name}%"))
    if map_name:
        stmt = stmt.where(ListingObservation.map_name == map_name)
    if start is not None:
        stmt = stmt.where(ListingObservation.observed_at >= start)
    if end is not None:
        stmt = stmt.where(ListingObservation.observed_at < end)

    stmt = stmt.order_by(ListingObservation.observed_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))
