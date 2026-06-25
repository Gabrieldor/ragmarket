from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import MapAliasCreate, MapAliasOut
from db.repository import add_map_alias, delete_map_alias, list_map_aliases
from db.session import get_db

router = APIRouter(prefix="/map-aliases", tags=["map-aliases"])


@router.get("", response_model=list[MapAliasOut])
def get_map_aliases(db: Session = Depends(get_db)):
    return list_map_aliases(db)


@router.post("", response_model=list[MapAliasOut], status_code=201)
def create_map_alias(payload: MapAliasCreate, db: Session = Depends(get_db)):
    raw_names = [name.strip() for name in payload.raw_map_names if name.strip()]
    if not raw_names:
        raise HTTPException(status_code=400, detail="At least one raw map name is required")
    rows = [
        add_map_alias(db, raw_map_name=raw_name, canonical_name=payload.canonical_name.strip())
        for raw_name in raw_names
    ]
    db.commit()
    return rows


@router.delete("/{alias_id}", status_code=204)
def remove_map_alias(alias_id: int, db: Session = Depends(get_db)):
    try:
        delete_map_alias(db, alias_id)
        db.commit()
    except ValueError:
        raise HTTPException(status_code=404, detail="Map alias not found")
