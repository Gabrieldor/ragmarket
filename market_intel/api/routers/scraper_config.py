import statistics
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.schemas import ScraperConfigOut, ScraperConfigUpdate
from collector.rollup_jobs import run_rollup_for_date
from db.models import ListingObservation
from db.repository import get_scraper_config
from db.session import get_db

router = APIRouter(prefix="/scraper-config", tags=["scraper-config"])


def _reflag_outliers(db: Session, factor: float) -> int:
    """Re-evaluate is_outlier for every observation using the new factor.
    Groups by (tracked_item_id, observed_at) to compute per-cycle medians.
    Returns the count of rows whose flag changed.
    """
    all_obs = list(db.scalars(select(ListingObservation)))
    groups: dict[tuple, list[ListingObservation]] = defaultdict(list)
    for obs in all_obs:
        groups[(obs.tracked_item_id, obs.observed_at)].append(obs)

    changed = 0
    for obs_list in groups.values():
        if len(obs_list) < 2:
            continue
        median = statistics.median(o.price for o in obs_list)
        threshold = factor * median
        for obs in obs_list:
            should_be = obs.price > threshold
            if should_be != obs.is_outlier:
                obs.is_outlier = should_be
                changed += 1
    return changed


@router.get("", response_model=ScraperConfigOut)
def get_config(db: Session = Depends(get_db)):
    return get_scraper_config(db)


@router.patch("", response_model=ScraperConfigOut)
def update_config(body: ScraperConfigUpdate, db: Session = Depends(get_db)):
    config = get_scraper_config(db)
    factor = max(1.1, body.outlier_factor)
    config.outlier_factor = factor
    _reflag_outliers(db, factor)
    db.flush()

    # Rebuild rollup stats (hourly/daily/map) for every date that has observations
    # so chart data reflects the new threshold immediately.
    dates = [
        r[0] for r in db.execute(
            select(func.date(ListingObservation.observed_at)).distinct()
        )
    ]
    for d in dates:
        run_rollup_for_date(db, date.fromisoformat(d))

    db.commit()
    return config
