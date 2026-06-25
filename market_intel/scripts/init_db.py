"""Create the database and apply all Alembic migrations.

Usage (from market_intel/, with the venv active):
    python scripts/init_db.py
"""

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

MARKET_INTEL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MARKET_INTEL_DIR))


def main() -> None:
    cfg = Config(str(MARKET_INTEL_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(MARKET_INTEL_DIR / "db" / "migrations"))
    command.upgrade(cfg, "head")
    print("Database is up to date.")


if __name__ == "__main__":
    main()
