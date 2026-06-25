# Ragnarok Market Intelligence Platform

Builds on the existing scraper in `D:\Rag\src` (untouched) to collect, store, and analyze
historical market data: price/supply trends over time, by hour, by weekday, weekend vs. weekday,
and by shop location. See `ARCHITECTURE.md` for the full design and `CHECKLIST.md` for build
status.

## Components

- **Collector** (`collector/runner.py`) — scrapes all active tracked items on a fixed cadence,
  persists observations, never sends notifications. Runs indefinitely.
- **Rollup & retention jobs** (`collector/rollup_jobs.py`, `collector/retention.py`,
  `collector/scheduled_jobs.py`) — nightly aggregation into `hourly_stats`/`daily_stats`/
  `map_stats`, and archival of raw observations past the retention window.
- **API** (`api/main.py`) — FastAPI backend serving item registration, raw observation search,
  and analytics endpoints.
- **Dashboard** (`frontend/`) — Next.js app for browsing the above.

## Setup

```bash
# from market_intel/
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .          # installs market_intel + editable ragwatch (../src)
.venv\Scripts\python.exe -m pip install -e ".[dev]"    # + pytest/httpx for running tests
.venv\Scripts\python.exe scripts\init_db.py            # creates market_intel.db, runs migrations

copy .env.example .env                                  # adjust DATABASE_URL / poll interval / etc.

cd frontend
npm install
copy .env.local.example .env.local                      # points the dashboard at the API
```

## Running

Three independent processes, typically run in separate terminals:

```bash
# Collector -- scrapes continuously
.venv\Scripts\python.exe collector\runner.py

# API
.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000

# Dashboard
cd frontend
npm run dev
```

Register items to track via the dashboard's "Item Registration" page, or with:

```bash
.venv\Scripts\python.exe scripts\seed_items.py path\to\item_list.txt   # one item name per line
```

## Nightly jobs

`collector/scheduled_jobs.py` runs the rollup job followed by the retention job. This project does
not run its own scheduler -- wire it up externally, off-peak relative to the collector:

- **Windows Task Scheduler**: daily trigger, action = `<path>\.venv\Scripts\python.exe
  <path>\collector\scheduled_jobs.py`
- **cron**: `0 3 * * * /path/to/.venv/bin/python /path/to/collector/scheduled_jobs.py`

Each job is also runnable standalone (`python collector/rollup_jobs.py`, `python
collector/retention.py`) and is idempotent/re-runnable for a given date.

## Tests

```bash
.venv\Scripts\python.exe -m pytest tests/ -v
```

Tests cover repository CRUD/cache logic, rollup aggregation correctness (including idempotency),
and API endpoints end-to-end against an in-memory database.

## Key design notes

- The original scraper in `src/` is depended on as an editable package (`pip install -e D:\Rag`),
  never modified. The adapter in `scraper_adapter/` subclasses `PlaywrightProvider` and overrides
  only the extraction hook.
- Shop location is resolved by clicking into a listing and reading the resulting detail modal
  (not a real `<iframe>`, and not a direct call to the underlying Next.js Server Action -- that
  was tried and abandoned as too fragile). Resolved locations are cached by (seller, shop, server)
  so repeat polls don't re-resolve known shops.
- `listings_observations` is the append-only source of truth; `hourly_stats`/`daily_stats`/
  `map_stats` are rebuildable rollups for fast dashboard queries, not authoritative.
- See `ARCHITECTURE.md` for the full schema, data flow, and rationale behind each decision.
