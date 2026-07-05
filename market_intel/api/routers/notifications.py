from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.schemas import (
    NotificationEventOut,
    NotificationSettingsOut,
    NotificationSettingsUpdate,
    WatchRuleCreate,
    WatchRuleOut,
    WatchRuleUpdate,
)
from db.models import NotificationSettings, WatchRule
from db.repository import (
    add_watch_rule,
    delete_watch_rule,
    find_tracked_item_by_name,
    get_notification_settings,
    list_notification_events,
    list_watch_rules,
    set_watch_rule_active,
    update_notification_settings,
)
from db.session import get_db
from notifications.rule_parser import parse_rule

router = APIRouter(tags=["notifications"])


def _mask_token(token: str | None) -> str | None:
    if not token:
        return None
    return f"...{token[-4:]}" if len(token) > 4 else "...****"


def _settings_out(config: NotificationSettings) -> NotificationSettingsOut:
    return NotificationSettingsOut(
        discord_token_masked=_mask_token(config.discord_token),
        channel_id=config.channel_id,
        user_mention=config.user_mention,
        local_sound=config.local_sound,
        variance_percent=config.variance_percent,
        min_items_below=config.min_items_below,
        rule_delay_seconds=config.rule_delay_seconds,
        store_type=config.store_type,
        server_type=config.server_type,
        max_pages=config.max_pages,
        updated_at=config.updated_at,
    )


@router.get("/watch-rules", response_model=list[WatchRuleOut])
def get_watch_rules(active_only: bool = False, db: Session = Depends(get_db)):
    return list_watch_rules(db, active_only=active_only)


@router.post("/watch-rules", response_model=WatchRuleOut, status_code=201)
def create_watch_rule(payload: WatchRuleCreate, db: Session = Depends(get_db)):
    try:
        item_name, operator, target_price, required_refine, required_slot, required_map = parse_rule(
            payload.raw
        )
        if required_map is not None and find_tracked_item_by_name(db, item_name) is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Map filtering requires '{item_name}' to be an actively tracked item "
                    "(add it on the Items page first)."
                ),
            )
        rule = add_watch_rule(
            db, raw=payload.raw.strip(), item_name=item_name, operator=operator, target_price=target_price,
            required_refine=required_refine, required_slot=required_slot, required_map=required_map,
        )
        db.commit()
        return rule
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/watch-rules/{rule_id}", response_model=WatchRuleOut)
def update_watch_rule(rule_id: int, payload: WatchRuleUpdate, db: Session = Depends(get_db)):
    if payload.is_active is None:
        rule = db.get(WatchRule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Watch rule not found")
        return rule
    try:
        rule = set_watch_rule_active(db, rule_id, payload.is_active)
        db.commit()
        return rule
    except ValueError:
        raise HTTPException(status_code=404, detail="Watch rule not found")


@router.delete("/watch-rules/{rule_id}", status_code=204)
def remove_watch_rule(rule_id: int, db: Session = Depends(get_db)):
    try:
        delete_watch_rule(db, rule_id)
        db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="Watch rule not found")


@router.get("/notifications/settings", response_model=NotificationSettingsOut)
def get_settings(db: Session = Depends(get_db)):
    config = get_notification_settings(db)
    db.commit()
    return _settings_out(config)


@router.patch("/notifications/settings", response_model=NotificationSettingsOut)
def patch_settings(payload: NotificationSettingsUpdate, db: Session = Depends(get_db)):
    config = update_notification_settings(db, **payload.model_dump())
    db.commit()
    return _settings_out(config)


@router.get("/notifications/events", response_model=list[NotificationEventOut])
def get_events(
    watch_rule_id: int | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
):
    return list_notification_events(
        db, watch_rule_id=watch_rule_id, event_type=event_type, limit=limit, offset=offset
    )
