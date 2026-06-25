"""Combined nightly entry point: rollup, then retention.

Intended to be invoked once a day by an external scheduler (cron on
Linux/macOS, Task Scheduler on Windows) -- this project does not run its own
scheduler process. Run after the day's collection is done, off-peak relative
to the collector's write activity, e.g.:

    Windows Task Scheduler: daily trigger -> action:
        "<path to .venv>\\Scripts\\python.exe" "<path>\\collector\\scheduled_jobs.py"

    cron: 0 3 * * * /path/to/.venv/bin/python /path/to/collector/scheduled_jobs.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from collector import retention, rollup_jobs  # noqa: E402

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Starting nightly rollup...")
    rollup_jobs.main()
    logger.info("Starting retention (archive + prune)...")
    result = retention.archive_and_prune()
    logger.info("Retention result: %s", result)


if __name__ == "__main__":
    main()
