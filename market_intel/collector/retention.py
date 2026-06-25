"""Retention job: archives raw observations older than the configured retention
window to compressed CSV files, then prunes them from listings_observations.
Nothing is hard-deleted without first being written to an archive file.

Run after rollup_jobs.py has processed the same dates, since the rollup tables
are the only remaining source of aggregate history once raw rows are pruned.
"""

import csv
import gzip
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from db.models import ListingObservation  # noqa: E402
from db.session import get_session  # noqa: E402
from settings import settings  # noqa: E402

logger = logging.getLogger(__name__)

ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "archive"


def archive_and_prune(cutoff_date: date | None = None) -> dict:
    cutoff_date = cutoff_date or (date.today() - timedelta(days=settings.raw_retention_days))
    cutoff_dt = datetime.combine(cutoff_date, datetime.min.time())

    with get_session() as session:
        rows = list(
            session.scalars(
                select(ListingObservation).where(ListingObservation.observed_at < cutoff_dt)
            )
        )
        if not rows:
            return {"archived": 0, "pruned": 0, "cutoff": cutoff_date.isoformat(), "file": None}

        ARCHIVE_DIR.mkdir(exist_ok=True)
        archive_path = ARCHIVE_DIR / f"observations_before_{cutoff_date.isoformat()}.csv.gz"
        fieldnames = [c.name for c in ListingObservation.__table__.columns]

        with gzip.open(archive_path, "wt", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({name: getattr(row, name) for name in fieldnames})

        ids = [row.id for row in rows]
        session.execute(delete(ListingObservation).where(ListingObservation.id.in_(ids)))

    return {
        "archived": len(rows),
        "pruned": len(ids),
        "cutoff": cutoff_date.isoformat(),
        "file": str(archive_path),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    result = archive_and_prune()
    logger.info("Retention result: %s", result)
