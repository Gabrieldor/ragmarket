"""Nightly retention job -- archiving and pruning old raw observations.

Rollup (hourly/daily/map stats) now runs automatically after every scrape cycle
inside the collector, so it no longer belongs here. This script only handles
retention and should be scheduled once a day, off-peak.

    Windows Task Scheduler: daily trigger -> action:
        "<path to .venv>\\Scripts\\python.exe" "<path>\\collector\\scheduled_jobs.py"

    cron: 0 3 * * * /path/to/.venv/bin/python /path/to/collector/scheduled_jobs.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import retention  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Starting retention (archive + prune)...")
    result = retention.archive_and_prune()
    logger.info("Retention result: %s", result)


if __name__ == "__main__":
    main()
