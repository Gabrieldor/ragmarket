# Ragnarok Market Intelligence Platform

Scrapes the Ragnarok Online LATAM marketplace on a fixed cadence, stores every observation,
rolls it up into fast-to-query stats, evaluates user-defined price watch rules, and posts
Discord alerts. A Next.js dashboard sits on top for browsing trends, maps, and item history.

See `ARCHITECTURE.md` for the full schema/data-flow design and `CHECKLIST.md` for build status.
This file covers **what's actually running today and how to work on it**.

## Components

| Component | Path | What it does |
|---|---|---|
| Collector | `collector/runner.py` | Scrapes all active tracked items sequentially, one cycle after another forever. Per item: persists observations, resolves shop locations (cached), rebuilds that day's rollup stats, and checks any watch rule pointed at that item — all immediately after that item finishes, not batched at cycle end. |
| Watch rules (untracked items) | `notifications/checker.py` | After the full cycle, checks watch rules for items that are *not* in the tracked-item registry (rules on tracked items were already handled per-item above). Fires Discord notifications on state transitions. |
| Rollup jobs | `collector/rollup_jobs.py` | Aggregates raw observations into `hourly_stats` / `daily_stats` / `map_stats`. Idempotent per date — safe to re-run. |
| Scraper adapter | `scraper_adapter/` | Subclasses the vendored `ragwatch` Playwright provider (from `../src`, never modified directly) to add per-listing detail + shop-location extraction. Location is read by clicking a listing card and parsing the resulting detail modal — not a raw API call, that was tried and abandoned as too fragile against frontend changes. |
| API | `api/main.py`, `api/routers/` | FastAPI backend. Key route groups: `/collector` (live status, pause/resume/retry), `/items`, `/observations`, `/analytics`, `/scraper-config`, `/sold-out`, `/map-aliases`, `/admin` (incl. IP rotation trigger). |
| Frontend | `frontend/` | Next.js dashboard — item registration, maps, data analysis, price watcher, audit/explorer views. |
| Notifications | `notifications/` | Discord bot (`discord_notifier.py`) + rule parsing/evaluation. `sound_notifier.py` is a Windows-only local-dev convenience; no-ops silently on Linux. |

## Operational behaviors worth knowing before you touch this

- **Rollup runs after every item**, not once a day — a change made 2026-07-08. Dashboard charts
  reflect the current cycle's data within minutes, not by the next day.
- **Watch rules for tracked items run immediately after that item scrapes**, using the
  observations just collected (no duplicate live scrape). Watch rules for items *not* in the
  tracked registry still run once, at the end of the cycle, via a live fetch.
- **IP auto-rotation**: if 100% of location-modal lookup attempts in a cycle fail (0 successes
  out of N attempts), the collector calls `/admin/rotate-ip`, which stops/starts the EC2 instance
  to get a fresh public IP. This assumes the failure is IP-based rate limiting — it will *not*
  fix a genuine site-frontend change (e.g. a listing card no longer opening its detail modal).
  Check `debug_captures/modal_failures/` (screenshot + HTML dump per failure, capped at the 200
  most recent) before assuming rotation is the fix.
- **The EC2 instance's public IP changes on every stop/start**, including from auto-rotation.
  A boot-time script (`notify_ip.py`, run via `market-intel-notify-ip.service`) posts the new IP
  to Discord and clears the collector's rate-limit backoff so it doesn't wait out a stale timer.
- **Never restart the collector mid-scrape.** SIGTERM during a Playwright page interaction kills
  the browser and any in-flight item. Check `journalctl -u market-intel-collector -n 5` (or the
  `/collector/status` API) for `state: scraping` vs `sleeping` first.

## Local development setup

Use this for editing code, running tests, or reproducing a bug — **not** for running the actual
service long-term (that's the AWS deployment below; this repo does not run local schedulers).

```bash
# from D:\Rag (repo root) -- installs the vendored ragwatch scraper package
pip install -e .

# from market_intel/
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"   # market_intel + pytest/httpx
.venv\Scripts\python.exe scripts\init_db.py            # creates market_intel.db, runs Alembic migrations

copy .env.example .env      # adjust DATABASE_URL / POLL_INTERVAL_SECONDS / etc.

cd frontend
npm install
copy .env.local.example .env.local   # NEXT_PUBLIC_API_BASE_URL -- baked in at build time, not runtime
```

Run the three processes in separate terminals:

```bash
.venv\Scripts\python.exe -m collector.runner              # collector
.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000  # API
cd frontend && npm run dev                                 # dashboard (localhost:3000)
```

Register items to track from the dashboard's item registration page, or seed a batch:

```bash
.venv\Scripts\python.exe scripts\seed_items.py path\to\item_list.txt   # one item name per line
```

Discord credentials (`discord_token`, `channel_id`, `user_mention`) are configured from the
dashboard's settings page — they're stored in the `notification_settings` DB table, not `.env`.

### Tests

```bash
.venv\Scripts\python.exe -m pytest tests/ -v
```

Covers repository CRUD/cache logic, rollup aggregation (including idempotency), notification
rule evaluation, sales/sold-out inference, and API endpoints end-to-end against an in-memory DB.

## Production deployment (AWS EC2)

This is how the real, always-on instance runs — see the repo-root `CLAUDE.md` for exact
commands, instance ID, and current SSH/IP-lookup steps. Summary:

- One t4g.small EC2 instance runs three systemd services, each auto-restarting:
  `market-intel-api` (uvicorn :8000), `market-intel-collector`
  (`python -m market_intel.collector.runner`), `market-intel-frontend` (`npm run start` :3000).
- Deploying a code change: sync the changed files to `/home/ubuntu/Rag/market_intel/...`, run any
  new Alembic migration (`.venv/bin/python scripts/init_db.py` from the `market_intel/` dir on the
  server), rebuild the frontend if frontend files changed (env var is build-time baked), then
  restart only the affected service(s) — never the collector while it's mid-scrape.
- `NEXT_PUBLIC_API_BASE_URL` only needs rebuilding if the API host changes; it does not need to
  track the EC2 instance's public IP if the frontend calls the API via `localhost` server-side.

### Docker (alternative, not the current production path)

`Dockerfile` + `docker-compose.yml` exist as an equivalent of the three local processes plus a
one-shot migration step, sharing one volume for the SQLite file (`docker compose up -d --build`
from `market_intel/`). The build context must be the repo root, since the image needs the
sibling `ragwatch` package (`../src`) installed as an editable dependency, same as local dev.
The live AWS instance currently runs the systemd services directly, not this compose stack.

## Key design notes

- `listings_observations` is the append-only source of truth; `hourly_stats` / `daily_stats` /
  `map_stats` are rebuildable rollups for fast dashboard queries, not authoritative — safe to
  wipe and regenerate via `rollup_jobs.py`.
- Shop location is cached by `(seller, shop, server)` so repeat polls don't re-resolve known
  shops; only genuinely new shop/seller pairs trigger a live modal-click lookup.
- If the site's HTML changes, the CSS-selector blocks are isolated: `SELECTORS` at the top of
  the vendored `playwright_provider.py`, and the equivalent block at the top of
  `scraper_adapter/location_action.py` for the location modal.
- See `ARCHITECTURE.md` for the full schema, data flow, and rationale behind each major decision.
