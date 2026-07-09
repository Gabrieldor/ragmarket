# Running this project locally

Step-by-step setup for a fresh machine. This gets you the collector, API, and dashboard
running against a local SQLite DB — no AWS account needed. (Production runs on AWS EC2;
see `README.md` for that.)

## Prerequisites

- **Python 3.10+** (project is developed against 3.12)
- **Node.js 20+** and npm
- **git**

Commands below are Windows (PowerShell/cmd) paths, matching how this repo is developed.
On macOS/Linux, swap `.venv\Scripts\python.exe` → `.venv/bin/python` and `copy` → `cp`.

## 1 — Get the repo

You need the repo root (contains the vendored `ragwatch` scraper in `src/`) and the
`market_intel/` subfolder (the actual platform). If you already have both, skip to step 2.

```bash
git clone <repo-url> Rag
cd Rag
```

## 2 — Python environment

```bash
cd Rag                      # repo root
pip install -e .            # installs the vendored `ragwatch` scraper package

cd market_intel
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"   # market_intel itself + pytest/httpx
.venv\Scripts\python.exe -m playwright install chromium   # downloads the headless browser binary
```

If `pip install -e ".[dev]"` fails looking for `ragwatch`, the step-1 install from the repo
root didn't take — re-run it before continuing.

## 3 — Configure environment

```bash
copy .env.example .env
```

Open `.env` and adjust if needed — the defaults work out of the box for local testing:

| Key | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./market_intel.db` | Fine as-is for local dev |
| `POLL_INTERVAL_SECONDS` | `600` | Lower this (e.g. `60`) locally if you want faster feedback loops |
| `SERVER_TYPE` / `STORE_TYPE` | `FREYA` / `BUY` | Which server/listing-type the scraper targets |
| `HEADLESS` | `true` | Set `false` to watch Playwright drive a visible browser window |
| `ITEM_DELAY_SECONDS` / `LOCATION_CLICK_DELAY_SECONDS` | `8.0` / `2.5` | Throttling — don't set to `0`, the live site rate-limits aggressively |

You do **not** need `boto3`/AWS credentials for local use — the IP-auto-rotation admin
endpoint will just fail loudly if triggered, everything else works without AWS.

## 4 — Initialize the database

```bash
.venv\Scripts\python.exe scripts\init_db.py
```

Creates `market_intel.db` and runs all Alembic migrations. Re-run this any time you pull
new migrations.

## 5 — Frontend setup

```bash
cd frontend
npm install
copy .env.local.example .env.local
```

`.env.local` sets `NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000` by default — correct for
local dev, no changes needed. (This value is baked in at build time, not read at runtime —
if you ever change it, restart `npm run dev` / rebuild.)

## 6 — Run it

Three separate terminals, all from `market_intel/`:

```bash
# Terminal 1 — collector (scrapes on a loop)
.venv\Scripts\python.exe -m collector.runner

# Terminal 2 — API
.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000

# Terminal 3 — dashboard
cd frontend
npm run dev
```

Open **http://localhost:3000** — you should see the dashboard. API docs (Swagger UI) are at
**http://localhost:8000/docs**.

## 7 — Track some items

The collector only scrapes items you've registered. Either:

- Use the dashboard's item registration page, or
- Seed a batch from a text file (one item name per line):
  ```bash
  .venv\Scripts\python.exe scripts\seed_items.py path\to\item_list.txt
  ```

Give the collector one full cycle (check its terminal output) to see data appear on the
dashboard.

## 8 — Optional: Discord notifications

Watch-rule alerts (price triggers) post to Discord. Configure this from the dashboard's
**Settings** page — `discord_token`, `channel_id`, `user_mention` are stored in the DB, not
`.env`. Skip this entirely if you don't need notifications; everything else still works.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: ragwatch` | Re-run step 2's `pip install -e .` from the **repo root**, not `market_intel/` |
| Playwright errors about missing browser | Re-run `playwright install chromium` |
| Collector logs constant scrape failures/timeouts | The live site may be rate-limiting — increase `ITEM_DELAY_SECONDS` in `.env` |
| Dashboard loads but shows no data | Make sure you've registered at least one tracked item (step 7) and let one full collector cycle finish |
| Port 8000 or 3000 already in use | Another instance is already running — stop it, or pass `--port` to uvicorn / set `PORT` for `next dev` |

## Stopping

`Ctrl+C` in each of the three terminals.
