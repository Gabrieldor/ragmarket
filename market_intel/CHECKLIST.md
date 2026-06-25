# Implementation Checklist — Ragnarok Market Intelligence Platform

Tracks progress against `ARCHITECTURE.md`. Check items off as they're completed; keep this file
up to date instead of relying on memory of what's done.

## 0. Foundation / Reuse setup

- [x] Add `pyproject.toml` to `D:\Rag` (root-level, flat `py-modules` mapping to `src/` —
      no `__init__.py` needed, zero changes inside `src/`)
- [x] Verify `pip install -e D:\Rag` works from `market_intel` (editable, points at `src/`)
- [x] Confirm `from playwright_provider import PlaywrightProvider` etc. import cleanly
- [x] Scaffold `market_intel/` folder structure (per ARCHITECTURE.md §5)
- [x] Set up `pyproject.toml` for `market_intel` itself + dedicated `.venv`
- [x] Set up `.env.example` (DB path, poll interval, etc.)

## 1. Database layer

- [x] Define SQLAlchemy models: `tracked_items`, `scrape_runs`, `shop_locations`,
      `listings_observations`, `hourly_stats`, `daily_stats`, `map_stats`
- [x] Set up Alembic migrations (initial migration generated + applied)
- [x] Enable WAL mode on the SQLite connection
- [x] Add indexes: (`tracked_item_id`,`observed_at`), (`ssi`), (`map_id`),
      (`seller_name`,`shop_name`,`server_name`) unique on `shop_locations` (corrected from
      `server_id` -- see note below)
- [x] Write `db/repository.py` query helpers (CRUD for tracked items, insert observations,
      cache lookup/upsert for `shop_locations`)
- [x] `scripts/init_db.py` — create DB + run migrations from a clean state
- [x] `scripts/seed_items.py` — optional helper to bulk-add tracked items (tested, idempotent)
- [x] Corrected `shop_locations` cache key from numeric `server_id` to `server_name` (the
      canonical UI-click location method only surfaces a server *name*, not a numeric id —
      squashed into a single clean initial migration since no real data existed yet)

## 2. Scraper adapter (wraps existing scraper, no modification to `src/`)

- [x] `scraper_adapter/provider_adapter.py` — subclasses `PlaywrightProvider`, overrides only the
      `_scrape_page` extraction hook; lifecycle/navigation/retry fully inherited
- [x] Extract additional card-level fields already present in the DOM: `data-id` (item id),
      `data-ssi` (listing id), shop name, seller name (previously discarded by `_EXTRACT_JS`) —
      verified against live site (`Elunium` search)
- [x] `scraper_adapter/location_action.py`:
  - [x] Attempted direct POST call to the Next.js Server Action — **abandoned**: requires
        replicating Next.js's full internal header set or it falls back to full-page render
  - [x] Implemented UI-click + modal-read as the canonical method (simpler, more robust)
  - [x] Selectors isolated in one block (`MODAL_INFO_ITEM`, `MODAL_WRAP`), mirrors `SELECTORS`
        convention in `playwright_provider.py`
  - [x] Confirmed only human-readable `map_name` (e.g. `prt_mk.gat`) is available via this method,
        not numeric `mapId` — `map_id` column stays nullable/unpopulated for now (see
        ARCHITECTURE.md §1)
- [x] Manual test against the live site: confirmed across multiple listings (map name, x/y,
      seller, server all correctly extracted)
- [x] Combined `scrape_item()` method: extracts cards + clicks only cache-miss (seller, shop)
      pairs within the same page session (via `dom_index` mapping), leaves cache-hit listings for
      the caller to fill in — smoke-tested live, confirmed different shops resolve to different
      maps/coordinates

## 3. Collector service

- [x] `collector/runner.py`:
  - [x] Load config via `settings.py` (env-based, mirrors existing `config.json` shape)
  - [x] Query `tracked_items WHERE is_active = 1` at the start of each cycle
  - [x] Scrape each tracked item's listings (card-level, via `scrape_item`)
  - [x] For each listing: check `shop_locations` cache by (seller_name, shop_name, server_name);
        on miss, click through and upsert cache
  - [x] Write all observations for the cycle, tagged with a `scrape_runs` row
  - [x] Track elapsed time spent per cycle
  - [x] Sleep `max(0, poll_interval - elapsed)` before next cycle
  - [x] Run indefinitely; graceful shutdown on SIGINT/SIGTERM (mirrors existing `main.py` pattern;
        Windows falls back to `KeyboardInterrupt` same as the original)
  - [x] No notification calls anywhere in this path
- [x] Manual test: ran 2 full cycles against 2 real tracked items (Elunium, Oridecon) live —
      cycle 1: 48 observations, 37 fresh location lookups; cycle 2: 59 cache hits, **0** fresh
      lookups, confirming the cache works as designed
- [ ] Verify rate-limit behavior is acceptable (no excessive 429s) at v1 scale over a longer,
      multi-hour soak test (not yet run — only 2 short manual cycles so far)

## 4. Rollup & retention jobs

- [x] Fixed the same `map_id`-vs-name issue in `MapStat` as `ShopLocation` (only `map_name` is
      ever captured, not a numeric id) — squashed into the migration before any real data existed
- [x] `collector/rollup_jobs.py`:
  - [x] Aggregates raw rows into `hourly_stats` for a given date
  - [x] Aggregates into `daily_stats` (with `weekday`/`is_weekend`)
  - [x] Aggregates into `map_stats`
  - [x] Idempotent / re-runnable — tested: re-running produced no duplicate rows
  - [x] Tested with 46 days of synthetic data (828 observations): produced 276 hourly rows, 46
        daily rows, 138 map rows; weekend-vs-weekday split correctly reflected a synthetic +500
        weekend price bump (25766 vs 25344 avg), confirming the weekday/weekend analysis works
- [x] `collector/retention.py`:
  - [x] Archives raw rows older than the configured cutoff to gzip CSV (not hard-delete)
  - [x] Prunes archived rows from the live table
  - [x] Tested: 270/828 rows archived + pruned at a 30-day cutoff; archive file verified readable
        with matching row count; `hourly_stats`/`daily_stats` confirmed untouched after pruning
- [ ] Schedule both jobs off-peak relative to the collector's write activity (cron/Task Scheduler
      wiring not yet done — jobs are runnable standalone via `python collector/rollup_jobs.py` /
      `python collector/retention.py`, but nothing invokes them automatically yet)

## 5. API (FastAPI)

- [x] `api/main.py` — app setup, DB session wiring (`get_db` dependency in `db/session.py`), CORS
- [x] `api/schemas.py` — Pydantic DTOs for items, observations, hourly/daily/map/seller/trend stats
- [x] `routers/items.py` — list/add tracked items, PATCH to enable/disable + set polling overrides
- [x] `routers/observations.py` — raw data explorer endpoint (filter by item/seller/shop/map/date
      range, paginated)
- [x] `routers/analytics.py`:
  - [x] Time analysis (avg/median/min/max by hour-of-day, aggregated across a date range)
  - [x] Weekday analysis + dedicated weekend-vs-weekday comparison (% difference)
  - [x] Map analysis (price by map, aggregated across a date range)
  - [x] Seller analysis (deviation from each day's market average — flags undercutters)
  - [x] Trend analysis (recent N days vs. prior N days, % change)
  - [ ] Supply analysis (quantity patterns by day/hour) — not yet a dedicated endpoint; the
        underlying data (`total_quantity`/`listing_count`) is already in `hourly_stats`/
        `daily_stats`, just needs a thin endpoint mirroring the hourly/weekday pattern endpoints
- [x] Manual test: full API server run against 46 days of synthetic data (1104 observations, 4
      sellers, 3 maps) — every endpoint exercised live via curl:
  - hourly/weekday endpoints returned correct aggregates (138 listings/hour bucket, 46 days)
  - weekend-vs-weekday showed +1.69% (matches the synthetic weekend price bump)
  - map analysis correctly differentiated avg price per map
  - seller analysis correctly identified the deliberately-undercutting synthetic seller
    ("yoquiero", biased -1500) as the top undercutter (-990 avg deviation), sorted first
  - trend endpoint returned a sane recent-vs-prior % change
- [x] Basic input validation + error responses verified live: invalid `item_id` type → 422
      (FastAPI's automatic path-type validation), out-of-range `days` on the trend endpoint → 422
      (existing `Query(ge=1, le=365)` constraint), nonexistent-but-valid `item_id` → 200 with
      empty arrays / null fields on every analytics endpoint (no 500s) — confirmed correct after
      ruling out an initial false alarm caused by testing against a DB with no tables yet

## 6. Dashboard (Next.js)

- [x] Project scaffold (`frontend/`, Next.js 16 App Router + TypeScript + Tailwind v4), shared
      layout/nav across all pages
- [x] Chart library: Recharts (line/bar charts for hourly, weekday, map comparisons)
- [x] Overview page — tracked items list with active/paused status, links to detail
- [x] Item detail page — hourly price chart (avg/min/max), weekday bar chart, weekend-vs-weekday
      stat card, trend stat card, seller table sorted by undercutting
- [x] Map analysis page — item selector + price-by-map bar chart and table
- [x] Raw data explorer page — filter by item/seller/shop/map, paginated table
- [x] Item registration page — add items, enable/disable, table of all tracked items
- [x] Delete tracked item (with confirmation) — permanently removes the item plus all its
      observations and rollup stats; verified live (create/delete/re-delete-404 round trip)
- [x] Real-time collector status banner on Overview — new `collector_status` single-row table the
      collector updates at each state transition (scraping/sleeping/rate_limited, with the current
      item name and next-cycle time); API endpoint treats a stale heartbeat (no update in
      `poll_interval + 60s`) as `offline` rather than trusting a possibly-dead process's last
      written state; dashboard polls it every 5s
- [x] Wired all pages to the FastAPI endpoints
- [x] Fixed Next.js 16 `allowedDevOrigins` dev-mode block (new in this version) that was silently
      preventing client bundle/data loading when accessed via `127.0.0.1`
- [x] Fixed Next.js 16 async `params` (dynamic route props are now `Promise`s) in the item detail
      route — split into a server `page.tsx` that awaits `params` and a client component for the
      actual data fetching/rendering
- [x] **Found and fixed a real backend race condition** via live browser testing (Playwright):
      `POST /items` followed immediately by the dashboard's post-submit `GET /items` refresh could
      return stale data missing the just-created item. Root cause: FastAPI's `yield`-based DB
      dependency commits *after* the response is already sent to the client, so a fast-following
      request can race ahead of the actual commit. Fixed by committing explicitly inside the
      `create_item`/`update_item` route handlers instead of relying on dependency teardown.
      Verified fixed with repeated live runs after the restart.
- [x] Production build (`npm run build`) verified clean, no type errors
- [x] Seller table on item detail now shows total item quantity (stock) per seller instead of
      listing/row count, per user feedback — added `total_quantity` to `SellerStatOut` and the
      `/analytics/{id}/sellers` aggregation; verified live (e.g. a seller with 1 listing but 300
      stock now shows 300, not 1)
- [x] Item throttling: `ITEM_DELAY_SECONDS` (between items) and `LOCATION_CLICK_DELAY_SECONDS`
      (between location-modal clicks within an item) added, mirroring the original scraper's
      `rule_delay` -- the new collector had dropped this protection entirely, which was likely the
      actual root cause of the HTTP 429s encountered during live testing
- [x] Escalating rate-limit backoff (3x, 9x, 27x..., capped at 4h) instead of a flat multiplier,
      persisted across process restarts via `scrape_runs` history -- a flat backoff proved
      insufficient when a live 429 recurred immediately after the original 25-minute wait
- [ ] Visual/manual review by you — everything above was verified via automated Playwright checks
      (page content assertions, network/console inspection) rather than a human looking at it

## 7. Hardening

- [x] Logging across collector, rollup/retention jobs (converted from bare `print` to `logging`),
      and API (via uvicorn)
- [x] Collector recovery after a mid-cycle crash:
  - [x] Refactored so each tracked item's observations commit immediately after that item
        finishes (was: batched in memory for the whole cycle) — a crash partway through a cycle
        now only loses the in-progress item, not everything scraped so far
  - [x] On startup, any `scrape_runs` left in `'running'` state by a previous crash are marked
        `'interrupted'`
- [x] `RateLimitError`/HTTP 429 handled explicitly in the collector loop: stops the current cycle
      early (doesn't crash), marks the run `'rate_limited'`, and **triples** the sleep before the
      next cycle (`RATE_LIMIT_BACKOFF_MULTIPLIER`)
- [x] Test suite (`tests/`, pytest + httpx, 16 tests, all passing):
  - [x] Repository CRUD + shop-location cache get/upsert/overwrite
  - [x] Rollup aggregation correctness (hourly/daily/map) including weekday/weekend classification
  - [x] API endpoints end-to-end (items CRUD, observations filtering, weekend-vs-weekday, trend)
        against an in-memory DB
  - [x] Caught **two more real bugs** while writing these tests: an in-memory SQLite test fixture
        without `StaticPool` was creating a separate empty DB per connection (classic SQLAlchemy
        pitfall under FastAPI's threaded TestClient); and the rollup functions' idempotency only
        held across separate process runs, not within a single uncommitted session, because
        `autoflush=False` meant a same-session re-run couldn't see its own pending inserts and
        tried to insert duplicates — fixed by flushing after each insert in
        `compute_hourly_stats`/`compute_daily_stats`/`compute_map_stats`
  - [x] Re-verified live against the real site after the crash-resilience refactor: 1 item, 22
        observations, 22 fresh location lookups, cycle completed cleanly
- [x] `README.md` for `market_intel/` — setup, running collector/API/dashboard, nightly job
      wiring, test instructions, key design notes

## Loose ends from earlier sections, resolved here

- [x] Supply analysis (flagged unchecked in Section 5): no new endpoint needed — `total_quantity`/
      `listing_count` were already included in the existing `/analytics/{id}/hourly` and
      `/analytics/{id}/weekday` responses, so supply-by-hour and supply-by-weekday are already
      answerable from data the dashboard already fetches. Skipped a redundant duplicate endpoint.
- [x] Job scheduling (flagged unchecked in Section 4): added `collector/scheduled_jobs.py`
      (rollup then retention, in one entry point) plus Windows Task Scheduler / cron wiring
      instructions in the README. This project intentionally does not run its own scheduler.

## Deferred (explicitly out of v1 scope — do not build yet)

- [ ] Data export (CSV/JSON/Excel)
- [ ] SELL-side tracking
- [ ] Anomaly/outlier detection
- [ ] Per-item adaptive polling cadence
- [ ] Multi-server support beyond FREYA
- [ ] Authentication
