# Ragnarok Market Intelligence Platform — Architecture & Implementation Plan

Status: **approved plan, pre-implementation**. This document is the source of truth for the
design; implementation should follow it unless reality (site behavior, schema needs) forces a
deviation — if it does, update this doc in the same change.

## 0. Constraints carried over from the existing project

- `D:\Rag\src` (the existing scraper) is **not to be modified**. It is treated as a trusted,
  external dependency.
- This is a fully separate project living in `D:\Rag\market_intel\`.
- **Superseded:** notifications were originally dropped entirely (no Discord/sound). The
  standalone price-watcher tool in `D:\Rag\src` (`main.py`/`monitor.py`/`discord_notifier.py`/
  `sound_notifier.py`) has since been fully ported into market_intel as the `notifications/`
  package, wired into the collector cycle (watch rules are checked first, before the
  tracked-item scrape, see `collector/runner.py`), with its own DB-backed watch-rule list,
  settings, and notification history — see the "Price Watcher" dashboard page. `src/` itself
  remains untouched; only its *logic* was ported, not the module.
- No external DB server — SQLite + SQLAlchemy, embedded.
- No authentication on the dashboard (internal tool, for now).
- Target scale for v1: **tens of tracked items, polling every 5–10 minutes**, with the
  architecture able to grow to "hundreds of items" later without a redesign (see §9).
- Track **BUY** listings only for v1 (schema supports SELL later with no migration needed —
  `store_type` is already a column, not an assumption baked into table shape).
- Raw observations retained at full resolution for **30 days**, then aggressively archived/rolled up
  (see §6).
- Export (CSV/JSON/etc.) is explicitly **deferred** — not part of v1 scope.

## 1. Findings from inspecting the live site (ground truth, not assumptions)

These were confirmed by live recon against `ro.gnjoylatam.com`, not guessed:

- The existing scraper (`playwright_provider.py`) only ever extracts `price` and `quantity` from
  result cards. Everything else below is **new** capture logic this project must build.
- Each result card (`li[data-id]`) already exposes, without any extra request:
  - `data-id` → the **item ID** (e.g. `757` for "Minério de Elunium" — confirmed via the
    thumbnail URL `.../item/2025/10/757.png`).
  - `data-ssi` → a long numeric string (e.g. `7654720332473943505`) — this is the **stable
    per-listing identifier** (`ssi` in the API response below). Solves the "no stable listing
    identity" problem entirely.
  - "Nome do Comércio" (shop name) and "Vendedor" (seller name) text, already rendered on the
    card.
- Clicking a card does **not** open a real `<iframe>` with a map. It opens a client-side modal
  (Radix UI dialog) that reveals: "Localização da loja" (map name + `x/y` coordinates as one
  string, e.g. `prt_mk.gat` / `163/255`), "Nome do Vendedor" (seller name), and "Informações do
  tipo" (server name, e.g. `FREYA`).
- **Implementation decision (superseded an earlier plan):** the modal click also triggers a
  Next.js Server Action (`POST` to the same page URL, `Next-Action: <build-specific hash>`
  header, body `[{"type":"store","params":{"svrId":...,"mapId":...,"ssi":"..."}}]`) which returns
  a clean JSON payload. A direct hand-crafted POST to this endpoint was tested and **abandoned**:
  without replicating Next.js's full internal header set (`Next-Router-State-Tree`, `Accept`,
  etc.) the server falls back to rendering the entire page instead of executing the action, making
  a faithful direct call fragile and high-maintenance. **The canonical method is UI-click
  simulation** — click the card, wait for the modal, read its text via one `page.evaluate`, then
  press `Escape` to close it. This was validated against the live site across multiple listings
  and is implemented in `scraper_adapter/location_action.py`.
- This means the per-listing numeric `itemId`/`svrId`/`mapId` values seen in the Server Action
  response are **not** captured by the UI-click method — only the human-readable `map_name`
  string (e.g. `prt_mk.gat`) is available. `map_id` remains a nullable column for a possible
  future static `map_name → map_id` lookup table, but is not populated in v1.
- This location data is **not** present in the initial page HTML/DOM — it is only obtainable by
  opening the modal. It is cheap (one click + one small DOM read), but it is a distinct
  interaction per *unseen* (seller, shop) combination, which is exactly what the
  `shop_locations` cache (§2) is for.
- Risk: the modal's CSS class selectors (`style_shop_info_content_wrap`, `style_shop_info__*`,
  `style_shop_info_content_name__*`) are isolated in `scraper_adapter/location_action.py`,
  mirroring the `SELECTORS` block convention in `playwright_provider.py` — edit only that block if
  the site's modal markup changes.

## 2. Location-fetching strategy (as agreed)

- On every poll, the card-level scrape already gives shop name + seller name for every listing
  for free.
- Maintain a `shop_locations` cache keyed by `(seller_name, shop_name)`. If a (seller, shop) pair
  has already been resolved to a map/position, **reuse the cached location** — do not re-fetch.
- Only call the location action for (seller, shop) pairs not yet in the cache.
- The poll loop targets a fixed cadence (e.g. every 10 minutes). Time spent on cache-miss location
  lookups during a cycle is **subtracted** from the sleep before the next cycle:
  `sleep_for = max(0, poll_interval_seconds - elapsed_seconds_this_cycle)`.
  This mirrors the existing `rule_delay`/`poll_interval` pattern in `monitor.py`, just elapsed-aware.

## 3. System architecture

```
┌───────────────────────┐        ┌──────────────────────────────┐
│  Existing Scraper       │ import │   Collector Service             │
│  D:\Rag\src (untouched)  │◀──────│   D:\Rag\market_intel\collector  │
│  - PlaywrightProvider    │        │   - reads tracked_items from DB │
│  - parser, config        │        │   - card scrape (reused logic)  │
└───────────────────────┘        │   - location lookup (new, §1-2) │
                                    │   - writes observations          │
                                    └──────────────┬─────────────────┘
                                                     │ SQLAlchemy
                                                     ▼
                                    ┌──────────────────────────────┐
                                    │   SQLite DB (WAL mode)         │
                                    │   raw + rollup + cache tables  │
                                    └──────────────┬─────────────────┘
                                                     │
                         ┌────────────────────────────┼────────────────────────┐
                         ▼                                                      ▼
              ┌──────────────────────┐                              ┌────────────────────┐
              │ FastAPI backend        │◀─────────────────────────────│  Rollup/retention    │
              │ (CRUD + analytics)     │                              │  jobs (scheduled)      │
              └─────────┬──────────────┘                              └────────────────────┘
                         │ REST/JSON
                         ▼
              ┌──────────────────────┐
              │ Next.js dashboard       │
              └──────────────────────┘
```

Two long-running processes share one SQLite file: the **collector** (scrape loop, write-only on
the hot path) and the **API** (read-mostly, plus item-registration writes). WAL mode lets the API
read while the collector writes.

## 4. Reuse strategy — depending on `D:\Rag\src` without modifying it

`src/` currently uses sibling imports (`from data_provider import ...`), so it cannot be imported
cleanly from outside `src/` as-is.

**Decision: package it.** Add a `pyproject.toml` + `__init__.py` to `D:\Rag\src` so it becomes
`pip install -e D:\Rag` from `market_intel`. This is packaging metadata only — no logic changes,
no behavior changes to the existing scraper. `market_intel` then does:

```python
from playwright_provider import PlaywrightProvider  # the existing, untouched class
```

and only ever **subclasses or wraps** it (e.g. `scraper_adapter/provider_adapter.py` adds a new
method for the location-action call) rather than editing `playwright_provider.py` directly.

If modifying `src/` for packaging turns out to be undesirable, fallback is runtime `sys.path`
injection from `market_intel` — fragile but truly zero-touch. Packaging is the recommended default;
flag if you'd rather not touch `src/` at all.

## 5. Folder structure

```
D:\Rag\                          ← existing scraper, untouched
  src/...
  config.json
  watches.json

D:\Rag\market_intel\             ← new project root
  ARCHITECTURE.md                ← this document
  pyproject.toml                 # depends on ../src as local editable package
  .env.example

  scraper_adapter/
    __init__.py
    provider_adapter.py          # wraps PlaywrightProvider; adds location-action call
    location_action.py           # isolated Next-Action constant + POST call + UI-click fallback
    selectors.py                 # any new selectors isolated here, mirrors src/ pattern

  db/
    models.py                    # SQLAlchemy ORM models
    session.py
    migrations/                  # Alembic
    repository.py                # query helpers shared by collector and API

  collector/
    runner.py                    # main loop: read tracked items → scrape → persist
    rollup_jobs.py                # nightly hourly/daily/map aggregation
    retention.py                  # archive/prune raw rows past 30 days

  api/
    main.py                      # FastAPI app
    routers/{items,observations,analytics}.py
    schemas.py                   # Pydantic DTOs

  frontend/                      # Next.js app
    app/{overview,items,trends,maps,explorer}/...

  scripts/
    init_db.py
    seed_items.py
```

## 6. Database schema (SQLite + SQLAlchemy)

**Why SQLite (pros/cons):**
- Pros: zero ops, single-file backup, fine for one collector + one dashboard reader, WAL mode
  allows concurrent reads during writes, trivially portable.
- Cons: single-writer lock (acceptable — one collector process), no native time-series features
  (continuous aggregates, compression, retention) — built manually here, weaker concurrent-write
  scaling than a server DB.
- Verdict for v1 scale (tens of items, 5–10 min polling): appropriate. Revisit if you add multiple
  collectors, multi-user concurrent writes, or need fast queries over 100M+ raw rows without
  rollups (see §9).

**Tables:**

`tracked_items`
- `id` PK, `item_name` (exact scrape string), `display_name`, `site_item_id` (the `itemId` field,
  confirmed meaning), `server_name`, `store_type` ('BUY' for v1), `is_active`, `poll_interval_override`
  (nullable), `created_at`, `updated_at`
- Unique index: (`item_name`, `server_name`, `store_type`)

`scrape_runs`
- `id` PK, `started_at`, `finished_at`, `status`, `items_attempted`, `items_succeeded`,
  `location_lookups_performed`, `error_message`

`shop_locations` (the cache keyed by seller+shop, per §2)
- `id` PK, `seller_name` (`itemSellerCharName`), `shop_name` (`storeName`), `server_id` (`svrId`),
  `map_id` (`mapId`), `map_name` (nullable, if resolvable), `x_pos` (`xpos`), `y_pos` (`ypos`),
  `first_seen_at`, `last_verified_at`
- Unique index: (`seller_name`, `shop_name`, `server_id`)

`listings_observations` (append-only fact table — core of the system)
- `id` PK, `tracked_item_id` FK, `scrape_run_id` FK, `observed_at` (indexed, the capture timestamp),
  `ssi` (the stable per-listing ID from `data-ssi`), `item_id` (site item ID), `price`, `quantity`
  (`itemCnt`), `seller_name`, `shop_name`, `server_id`, `server_name`, `store_type`
  (`marketStoreTypeCode`), `map_id`, `map_name`, `x_pos`, `y_pos`, `location_source`
  ('cache' | 'fresh_lookup'), `page_num`, `rank_on_page`
- `map_id`/`map_name`/`x_pos`/`y_pos` are denormalized onto each row from the `shop_locations`
  cache at write time (so historical rows aren't affected if a seller moves shop later — moves
  show up as new cache entries with a later `first_seen_at`).
- Indexes: (`tracked_item_id`, `observed_at`), (`ssi`), (`map_id`)

`hourly_stats` / `daily_stats` (rollups, rebuildable from raw — not authoritative)
- keyed by (`tracked_item_id`, `date`, `hour` or `weekday`/`is_weekend`): `avg_price`,
  `median_price`, `min_price`, `max_price`, `total_quantity`, `listing_count`

`map_stats` (rollup)
- (`tracked_item_id`, `map_id`, `period_start`, `period_end`): `avg_price`, `listing_count` —
  supports "Prontera vs Alberta" style comparisons without scanning raw data each time.

**Retention:** raw `listings_observations` kept at full resolution for 30 days; nightly job rolls
data into `hourly_stats`/`daily_stats`/`map_stats` and archives/prunes raw rows older than the
window (archive to compressed files rather than hard-delete, so nothing is permanently lost).

## 7. Data flow (per scrape cycle)

1. Collector loads config (reused from `src/`) + queries `tracked_items WHERE is_active = 1`.
2. For each tracked item: card-level scrape (reused capability) → for each listing, look up
   `(seller_name, shop_name)` in `shop_locations`; on cache miss, call the location action
   (§1–2), write the result into `shop_locations`, mark `location_source = 'fresh_lookup'`.
3. Write all observations for the cycle in one transaction, tagged with a `scrape_runs` row.
4. Compute elapsed time spent on cache-miss lookups this cycle; sleep
   `max(0, poll_interval - elapsed)` before the next cycle (§2). Repeat indefinitely.
5. Nightly: rollup job aggregates the previous day's raw data; retention job archives/prunes raw
   rows older than 30 days.

## 8. Analytics & dashboard

Unchanged from the original proposal — summarized here for completeness:

- **Time analysis** (avg/median/min/max by hour) → `hourly_stats`.
- **Weekday/weekend analysis** → `daily_stats` (has `weekday`/`is_weekend`).
- **Supply analysis** (e.g. low supply on Tuesdays) → same rollups, using `total_quantity`/`listing_count`.
- **Seller analysis** (undercutting sellers) → query raw `listings_observations` grouped by
  `seller_name`, compared against the concurrent market average — a dedicated query/service, not
  a rollup table, since it's seller-centric rather than time-bucket-centric.
- **Map analysis** → `map_stats` rollup, drill into raw table for distribution/outliers.
- **Trend analysis** (e.g. "+18% over 30 days") → compare `daily_stats` averages between two
  periods, computed in the API layer, not stored.

**Stack:** FastAPI + Next.js. **Charts:** Recharts for line/bar/area trend charts; ECharts (via
`echarts-for-react`) if an hour×weekday heatmap is wanted (a natural fit for "behavior by hour"
and "by weekday" combined).

**Pages:** Overview, Item detail (history + hour/weekday heatmap + seller table), Market trend,
Map analysis, Raw data explorer (filter/sort over `listings_observations`), Item registration
(add/enable/disable tracked items, per-item polling overrides).

Export is explicitly deferred — no UI/endpoint for it in v1.

## 9. Scalability & migration path

Back-of-envelope at v1 scale (tens of items, 5–10 min polling, ~10 listings/item): low millions of
raw rows per year — comfortably within SQLite's range, especially with the 30-day raw retention
window keeping the live table small.

If scale grows to "hundreds of items": still fine for SQLite *if* rollups are used for dashboard
queries (raw table should not be queried directly for aggregates at that scale). SQLite becomes
insufficient when: multiple concurrent collector processes are needed, the dashboard becomes
multi-user with heavy concurrent writes, or raw-table queries need to stay fast without rollups at
100M+ rows. Migration path: SQLAlchemy already abstracts the dialect — swap the connection string
to Postgres (optionally TimescaleDB for `listings_observations`) and run Alembic migrations;
application/API code should not need to change.

## 10. Risks & challenges

- **`Next-Action` hash is build-specific** and will break on site redeploys — isolate it, build a
  UI-click fallback, and treat it like the existing `SELECTORS` block (one place to fix).
- **Map name resolution**: confirm during Phase 1 whether a human-readable map name is reliably
  available, or only `mapId` (may need a static `mapId → mapName` lookup table maintained
  manually).
- **Rate limiting**: the existing scraper already encounters HTTP 429s under load (see
  `RateLimitError` in `playwright_provider.py`). Location lookups add request volume on
  cache-misses; the cache should keep this bounded, but the elapsed-time-aware sleep (§2) is the
  safety valve — must be implemented correctly from the start.
- **SQLite write contention** if the collector and rollup job run concurrently — mitigate with WAL
  mode and scheduling rollups off-peak.

## 11. Implementation phases

1. **Foundation** — package `src/` as an installable dependency, DB schema + Alembic migrations,
   item registration CRUD (API only, no scraping yet).
2. **Collector v1** — reuse existing card-level scraping, persist price/quantity/shop/seller fields
   (already available on the card), no location yet, no notifications.
3. **Location lookup** — implement the action-call adapter (§1–2), `shop_locations` cache,
   elapsed-aware cadence; validate against the live site and confirm rate-limit behavior.
4. **Rollup + retention jobs**.
5. **Analytics API** (time/weekday/supply/seller/map/trend endpoints).
6. **Dashboard** — overview → item detail → explorer → trend/map pages → registration page.
7. **Hardening** — error handling, logging, recovery from collector crashes mid-cycle.

## 12. Future improvements (explicitly out of scope for v1)

- Data export (CSV/JSON/Excel) — deferred per your decision; revisit if needed.
- SELL-side tracking (schema already supports it, just not populated in v1).
- Anomaly/outlier detection on price spikes.
- Per-item custom polling cadence based on observed volatility.
- Multi-server support beyond FREYA, if relevant.
- Authentication, if ever exposed beyond local use.
