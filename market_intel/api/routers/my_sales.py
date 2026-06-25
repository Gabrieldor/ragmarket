from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import (
    ItemCostBasisCreate,
    ItemCostBasisOut,
    MyListingSessionOut,
    MySalesByHourOut,
    MySalesByItemOut,
    MySalesByMapOut,
    MySalesSummaryOut,
    MyStatusBreakdownOut,
    VendorAliasCreate,
    VendorAliasOut,
)
from db.models import MyListingSession, MySaleEvent, TrackedItem
from db.repository import (
    add_vendor_alias,
    dismiss_my_listing_session,
    get_current_cost_basis,
    list_vendor_aliases,
    mark_shop_removed,
    remove_vendor_alias,
    restore_my_listing_session,
    set_item_cost_basis,
)
from db.session import get_db

router = APIRouter(prefix="/my-sales", tags=["my-sales"])


@router.get("/aliases", response_model=list[VendorAliasOut])
def get_aliases(db: Session = Depends(get_db)):
    return list_vendor_aliases(db)


@router.post("/aliases", response_model=VendorAliasOut, status_code=201)
def create_alias(payload: VendorAliasCreate, db: Session = Depends(get_db)):
    try:
        alias = add_vendor_alias(db, payload.alias_name)
        db.commit()
        return alias
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/aliases/{alias_id}", status_code=204)
def delete_alias(alias_id: int, db: Session = Depends(get_db)):
    try:
        remove_vendor_alias(db, alias_id)
        db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="Vendor alias not found")


@router.get("/cost-basis/{item_id}", response_model=ItemCostBasisOut | None)
def get_cost_basis(item_id: int, db: Session = Depends(get_db)):
    return get_current_cost_basis(db, item_id)


@router.post("/cost-basis/{item_id}", response_model=ItemCostBasisOut, status_code=201)
def create_cost_basis(item_id: int, payload: ItemCostBasisCreate, db: Session = Depends(get_db)):
    if db.get(TrackedItem, item_id) is None:
        raise HTTPException(status_code=404, detail="Tracked item not found")
    row = set_item_cost_basis(db, item_id, payload.cost_per_unit)
    db.commit()
    return row


def _to_session_out(row: MyListingSession, item_name: str) -> MyListingSessionOut:
    revenue = row.total_quantity_sold * row.price
    profit = (
        revenue - row.total_quantity_sold * row.cost_per_unit if row.cost_per_unit is not None else None
    )
    return MyListingSessionOut(
        id=row.id,
        tracked_item_id=row.tracked_item_id,
        item_name=item_name,
        ssi=row.ssi,
        seller_name=row.seller_name,
        shop_name=row.shop_name,
        map_name=row.map_name,
        price=row.price,
        window_start=row.window_start,
        window_end=row.window_end,
        initial_quantity=row.initial_quantity,
        last_known_quantity=row.last_known_quantity,
        total_quantity_sold=row.total_quantity_sold,
        status=row.status,
        ended_reason=row.ended_reason,
        cost_per_unit=row.cost_per_unit,
        revenue=revenue,
        profit=profit,
        dismissed=row.dismissed,
        dismissed_at=row.dismissed_at,
    )


@router.get("/sessions", response_model=list[MyListingSessionOut])
def get_sessions(
    tracked_item_id: int | None = None,
    status: str | None = None,
    start: date | None = None,
    end: date | None = None,
    include_dismissed: bool = False,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """The raw log of every tracked listing under a registered vendor alias. Dismissed
    (soft-deleted, see dismiss_session) entries are excluded by default -- pass
    include_dismissed=true for the audit view.
    """
    stmt = select(MyListingSession)
    if tracked_item_id is not None:
        stmt = stmt.where(MyListingSession.tracked_item_id == tracked_item_id)
    if status is not None:
        stmt = stmt.where(MyListingSession.status == status)
    if not include_dismissed:
        stmt = stmt.where(MyListingSession.dismissed.is_(False))
    if start is not None:
        stmt = stmt.where(MyListingSession.window_start >= start.isoformat())
    if end is not None:
        stmt = stmt.where(MyListingSession.window_start < (end + timedelta(days=1)).isoformat())
    stmt = stmt.order_by(MyListingSession.window_start.desc()).offset(offset).limit(limit)

    rows = list(db.scalars(stmt))
    item_names = {item.id: item.item_name for item in db.scalars(select(TrackedItem))}
    return [_to_session_out(row, item_names.get(row.tracked_item_id, "?")) for row in rows]


@router.delete("/sessions/{session_id}", response_model=MyListingSessionOut)
def dismiss_session(session_id: int, db: Session = Depends(get_db)):
    """Soft-deletes a bad My Sales entry (e.g. a listing the user manually pulled rather
    than sold). Kept in the DB for audit purposes -- see dismiss_my_listing_session.
    """
    try:
        row = dismiss_my_listing_session(db, session_id)
        db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="My listing session not found")
    item = db.get(TrackedItem, row.tracked_item_id)
    return _to_session_out(row, item.item_name if item else "?")


@router.post("/sessions/{session_id}/mark-shop-removed", response_model=MyListingSessionOut)
def mark_session_shop_removed(session_id: int, db: Session = Depends(get_db)):
    """Marks a session as manually closed by the user (shop pulled, not a real sellout).
    Corrects the sold quantity and enables the 24h continuation window so the next relist
    from the same seller is merged into this session rather than counted separately.
    """
    try:
        row = mark_shop_removed(db, session_id)
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    item = db.get(TrackedItem, row.tracked_item_id)
    return _to_session_out(row, item.item_name if item else "?")


@router.post("/sessions/{session_id}/restore", response_model=MyListingSessionOut)
def restore_session(session_id: int, db: Session = Depends(get_db)):
    """Reverses a dismiss."""
    try:
        row = restore_my_listing_session(db, session_id)
        db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="My listing session not found")
    item = db.get(TrackedItem, row.tracked_item_id)
    return _to_session_out(row, item.item_name if item else "?")


@router.get("/status-summary", response_model=list[MyStatusBreakdownOut])
def status_summary(db: Session = Depends(get_db)):
    """Counts/quantities of MyListingSession rows by status -- for the sold-out audit view
    (see TODO #3). Dismissed entries are excluded, same as /sessions by default.
    """
    rows = list(db.scalars(select(MyListingSession).where(MyListingSession.dismissed.is_(False))))
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"count": 0, "qty": 0})
    for row in rows:
        bucket = buckets[row.status]
        bucket["count"] += 1
        bucket["qty"] += row.total_quantity_sold
    return [
        MyStatusBreakdownOut(status=status, session_count=b["count"], total_quantity_sold=b["qty"])
        for status, b in sorted(buckets.items())
    ]


@router.get("/summary", response_model=MySalesSummaryOut)
def get_summary(
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
):
    """Aggregated 'my sales' metrics, compiling all registered vendor aliases together:
    total revenue/profit, breakdown by item, by map, and by hour-of-day (when sales happen).
    """
    stmt = select(MyListingSession).where(MyListingSession.dismissed.is_(False))
    if start is not None:
        stmt = stmt.where(MyListingSession.window_start >= start.isoformat())
    if end is not None:
        stmt = stmt.where(MyListingSession.window_start < (end + timedelta(days=1)).isoformat())
    sessions = list(db.scalars(stmt))

    item_names = {item.id: item.item_name for item in db.scalars(select(TrackedItem))}

    by_item_qty: dict[int, int] = defaultdict(int)
    by_item_revenue: dict[int, float] = defaultdict(float)
    by_item_cost: dict[int, float] = defaultdict(float)
    by_item_missing_cost: dict[int, bool] = defaultdict(bool)
    by_map_qty: dict[str, int] = defaultdict(int)
    by_map_revenue: dict[str, float] = defaultdict(float)

    for s in sessions:
        revenue = s.total_quantity_sold * s.price
        by_item_qty[s.tracked_item_id] += s.total_quantity_sold
        by_item_revenue[s.tracked_item_id] += revenue
        if s.cost_per_unit is None:
            by_item_missing_cost[s.tracked_item_id] = True
        else:
            by_item_cost[s.tracked_item_id] += s.total_quantity_sold * s.cost_per_unit

        map_key = s.map_name or "unknown"
        by_map_qty[map_key] += s.total_quantity_sold
        by_map_revenue[map_key] += revenue

    by_item = [
        MySalesByItemOut(
            tracked_item_id=item_id,
            item_name=item_names.get(item_id, "?"),
            quantity_sold=qty,
            revenue=by_item_revenue[item_id],
            profit=None if by_item_missing_cost[item_id] else by_item_revenue[item_id] - by_item_cost[item_id],
        )
        for item_id, qty in by_item_qty.items()
    ]
    by_map = [
        MySalesByMapOut(map_name=map_name, quantity_sold=qty, revenue=by_map_revenue[map_name])
        for map_name, qty in by_map_qty.items()
    ]

    session_ids = [s.id for s in sessions]
    by_hour_qty: dict[int, int] = defaultdict(int)
    if session_ids:
        events = list(db.scalars(select(MySaleEvent).where(MySaleEvent.session_id.in_(session_ids))))
        for event in events:
            by_hour_qty[event.occurred_at.hour] += event.quantity_sold
    by_hour = [
        MySalesByHourOut(hour=hour, quantity_sold=qty) for hour, qty in sorted(by_hour_qty.items())
    ]

    total_quantity_sold = sum(by_item_qty.values())
    total_revenue = sum(by_item_revenue.values())
    total_profit = None if any(by_item_missing_cost.values()) else total_revenue - sum(by_item_cost.values())

    return MySalesSummaryOut(
        total_quantity_sold=total_quantity_sold,
        total_revenue=total_revenue,
        total_profit=total_profit,
        by_item=by_item,
        by_map=by_map,
        by_hour=by_hour,
    )
