from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import TrackedItemCreate, TrackedItemOut, TrackedItemUpdate
from db.repository import add_tracked_item, delete_tracked_item, list_tracked_items
from db.models import TrackedItem
from db.session import get_db

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[TrackedItemOut])
def get_items(active_only: bool = False, db: Session = Depends(get_db)):
    return list_tracked_items(db, active_only=active_only)


@router.post("", response_model=TrackedItemOut, status_code=201)
def create_item(payload: TrackedItemCreate, db: Session = Depends(get_db)):
    try:
        item = add_tracked_item(
            db,
            item_name=payload.item_name,
            server_name=payload.server_name,
            store_type=payload.store_type,
            display_name=payload.display_name,
            poll_interval_override=payload.poll_interval_override,
        )
        # Commit explicitly here rather than relying on the get_db dependency's
        # post-yield commit, which FastAPI runs *after* the response has already
        # been sent -- a client that immediately re-fetches (e.g. the dashboard's
        # post-submit refresh) can otherwise race ahead of the actual commit and
        # read stale data.
        db.commit()
        return item
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/{item_id}", response_model=TrackedItemOut)
def update_item(item_id: int, payload: TrackedItemUpdate, db: Session = Depends(get_db)):
    item = db.get(TrackedItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Tracked item not found")
    if payload.is_active is not None:
        item.is_active = payload.is_active
    if payload.poll_interval_override is not None:
        item.poll_interval_override = payload.poll_interval_override
    if payload.sold_out_enabled is not None:
        item.sold_out_enabled = payload.sold_out_enabled
    db.commit()
    return item


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)):
    """Permanently deletes a tracked item and all its observations/rollup stats.
    Irreversible -- the dashboard requires explicit confirmation before calling this.
    """
    try:
        delete_tracked_item(db, item_id)
        db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="Tracked item not found")
