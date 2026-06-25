# Cloud Migration Runbook — Market Intelligence Platform

Status: **planning, not started**. This is a living document — check items off as completed,
and add notes/decisions inline as they're made, so a fresh session can pick up exactly where the
last one left off without re-deriving context. Read this whole file before doing anything when
resuming.

## Goal

Run the full stack (Collector, API, Dashboard, and the price-watcher's Discord/sound notifier)
24/7 on a cloud VM instead of the user's local Windows PC — so it survives PC sleep/shutdown, and
no longer depends on Windows Task Scheduler.

## Decisions made so far

- **Target platform: Oracle Cloud "Always Free" tier** (Ampere A1 ARM VM). Chosen over paid VPSes
  (Hetzner CX22 ~€4.59/mo was the fallback recommendation) because it's genuinely free 24/7.
  **Known risk**: Always Free Ampere capacity is frequently unavailable ("out of host capacity")
  depending on region — if provisioning keeps failing after reasonable retries, fall back to
  Hetzner CX22 (2 vCPU/4GB, ~€4.59/mo) without re-deriving the comparison; see prior chat history
  for the full VPS price comparison if needed.
- **Provisioning tool: Terraform** (already installed locally, confirmed via `terraform` on
  PATH), using the OCI provider — declarative, repeatable, easy to tear down/recreate, preferred
  over driving the OCI CLI by hand.
- **Containerization already built locally** (this session, see `D:\Rag\market_intel\`):
  - `Dockerfile` — shared image for API + collector. Build context must be the repo root
    (`D:\Rag`), since it installs the sibling `ragwatch` package (`D:\Rag\src`) editable first,
    then `market_intel` itself + `playwright install --with-deps chromium`.
  - `frontend/Dockerfile` — Next.js multi-stage build. **`NEXT_PUBLIC_API_BASE_URL` is baked in
    at build time** and must be the server's public IP/domain, not an internal Docker hostname.
  - `docker-compose.yml` — `migrate` (one-shot `scripts/init_db.py`) → `api` + `collector` (both
    depend on `migrate` completing) + `frontend`, sharing one named volume
    (`market_intel_data`) for the SQLite file.
  - Compose file syntax validated locally via `docker compose config` (clean). **Not yet build-
    verified** — Docker Desktop's daemon wasn't running locally when this was written; a full
    `docker compose build` has not been confirmed to succeed end-to-end.
- **Credential handling**: Oracle automation uses an API signing key pair (tenancy/user OCIDs +
  fingerprint + private key), not console username/password. The user should generate this
  themselves (`oci setup config` or via the console) so the private key never passes through
  chat — only the resulting config *values* (not the key file contents) get shared here.
- **Known risk — cloud IP blacklisting**: cloud-provider IP ranges (Oracle, AWS, etc.) are
  commonly blocked or fingerprinted by anti-bot/WAF protection, and `ro.gnjoylatam.com` is a
  Next.js site that already does some bot-detection (see `ARCHITECTURE.md` §1 on the Server
  Action / header fragility). There is no guarantee the Oracle instance's assigned IP can even
  reach the catalog site before any container work is worth doing — see the new check at the top
  of Phase 3.
- **Open question #4 resolved (2026-06-24)**: code delivery via **git repo** — `git init` at
  `D:\Rag`, push to a new private GitHub/GitLab repo, `git clone` on the VM.
- **Open question #5 resolved (2026-06-24)**: **start fresh** — do not migrate the local
  `market_intel.db`; the cloud instance boots with an empty DB via `scripts/init_db.py`.
- **Open question #1 resolved (2026-06-24)**: user **already has** an Oracle Cloud account with
  Always Free resources available — skip account creation in Phase 1.
- **Open question #6 resolved (2026-06-24)**: **plain IP for now** (`http://<public-ip>:3000`/
  `:8000`) — Phase 6 (domain + HTTPS) is deferred, not in scope for this pass.
- **Not yet decided / not yet done**: open questions #2 (region), #3 (API credentials), #7
  (Discord vs. local sound) — and everything in the checklist below.

## Open questions to resolve with the user (ask early, in this order)

These block specific steps below — ask before attempting that step, don't guess:

1. **Oracle account status**: does the user already have an Oracle Cloud account with Always
   Free resources available, or does one need to be created from scratch (email verification,
   credit card for identity verification only, region selection)?
2. **Region choice**: Always Free Ampere capacity varies a lot by region. Ask if they have a
   preference (e.g. proximity to the Ragnarok server's host country for latency) or if "whichever
   region actually has capacity" is fine.
3. **API key credentials**: walk them through generating the key pair themselves; collect tenancy
   OCID, user OCID, fingerprint, region, and the *path* to the private key file (never the key
   contents) — these go into `~/.oci/config`, not into this repo or chat history.
4. **Code delivery to the VM**: `D:\Rag` is **not currently a git repository** (confirmed
   2026-06-24 — `git rev-parse` fails). Ask whether to:
   - (a) initialize a git repo and push to a new private GitHub/GitLab repo, then `git clone` on
     the VM (cleaner for future updates: `git pull` + `docker compose up -d --build`), or
   - (b) `scp`/`rsync` the directory straight to the VM (no new remote-hosting account needed,
     but updates become manual re-syncs).
   Recommend (a) if the user is willing to create a repo (even a private one) — much easier to
   maintain. Default to (b) only if they explicitly don't want a remote git host involved.
5. **Existing data migration**: the user has a real, populated `market_intel.db` locally (active
   tracked items, history, watch rules, map aliases). Ask explicitly: copy this file to the
   server's persistent volume before first boot (preserves all history), or start the cloud
   instance with a fresh empty DB? Default recommendation: migrate the real file — re-running
   `scripts/init_db.py`'s migrations against the copied file is safe and expected.
6. **Domain name**: does the user want a domain pointed at the server (with HTTPS via
   Caddy/nginx + Let's Encrypt), or is plain `http://<public-ip>:3000` acceptable for now? Affects
   whether Step 9 (reverse proxy + TLS) is in scope for this pass or deferred.
7. **Discord vs. local sound for the price watcher**: `local_sound` (winsound beeps) obviously
   won't be audible/useful on a headless cloud VM with no one listening. Confirm before going
   live that `local_sound` should be switched to `false` with real Discord credentials configured
   via the Settings page (`/notifications/settings`) — otherwise notifications will silently no-op
   server-side (the code calls `winsound.Beep`, which will just do nothing / log only on Linux,
   no error, but the user gets nothing).

## Step-by-step plan

### Phase 0 — Local prep (can be done without any Oracle account)

- [ ] Start Docker Desktop locally and run `docker compose build` (from `market_intel/`) to
      confirm the existing `Dockerfile`/`frontend/Dockerfile` actually build end-to-end. Fix any
      issues found (this was not yet verified as of 2026-06-24).
- [ ] Resolve open question #4 (code delivery method). If git: `git init` at `D:\Rag` (repo root,
      so both `src/` and `market_intel/` are in one repo — they're already coupled via the
      editable-install relationship), add a `.gitignore` (`*.db`, `.venv/`, `node_modules/`,
      `.next/`, `__pycache__/`, `logs/`, `*.db-wal`, `*.db-shm`), commit, create the remote, push.
- [ ] Resolve open question #5 (data migration plan) — if migrating real data, decide now whether
      to copy `market_intel.db` via `scp` after the VM exists, or bundle it some other way. (Just
      a decision now; the actual copy happens in Phase 3.)

### Phase 1 — Oracle Cloud account + credentials

- [ ] Resolve open question #1 (account status). If new: user creates the account (requires
      identity verification, typically a card with no charge for Always Free resources).
- [ ] Resolve open question #2 (region).
- [ ] User generates an API signing key pair and runs `oci setup config` (or equivalent),
      producing `~/.oci/config` + key file. **Collect only**: tenancy OCID, user OCID,
      fingerprint, region, key file path — paste these values (not the key itself) into this
      session when resuming.
- [ ] Confirm Always Free service limits are enabled for the chosen tenancy/region (sometimes
      requires explicitly checking "Always Free eligible" resources in the console).

### Phase 2 — Provision infrastructure (Terraform)

- [ ] Write Terraform config (new directory, e.g. `D:\Rag\infra\oracle\`) for:
  - VCN + subnet + internet gateway + route table.
  - Security list / Network Security Group opening: 22 (SSH), 8000 (API), 3000 (frontend) — or
    just 80/443 if a reverse proxy is in scope (see open question #6).
  - One Ampere A1 Always Free compute instance (Ubuntu 22.04 or 24.04 LTS image), boot volume
    sized within the Always Free block-storage allowance.
  - Output the instance's public IP.
- [ ] `terraform init` / `terraform plan` — review the plan with the user before `apply` (this is
      a real provisioning action, even if free-tier; confirm before applying, per this project's
      "confirm before actions with external/billing effects" norm).
- [ ] `terraform apply`. **If "out of host capacity" errors occur**: this is a known Oracle
      Always-Free limitation, not a config bug — retry, try a different availability domain, or
      escalate to the Hetzner fallback (re-quote current Hetzner pricing if it's been a while
      since the original comparison, prices drift).
- [ ] Note the instance's public IP here once provisioned: `<TBD>`.

### Phase 3 — Server setup

- [ ] SSH into the instance (`ssh ubuntu@<public-ip>`, key-based auth from the Terraform-managed
      instance).
- [ ] **Gate check — do this before any Docker/container work.** Confirm the instance's IP can
      actually reach the target catalog site at all; cloud-provider IP ranges (Oracle included)
      are a common target for anti-bot blocking, and there's no point containerizing/porting
      anything if the VM is blacklisted before we even start. From the freshly-SSH'd-into
      instance:
  - `curl -I https://ro.gnjoylatam.com/pt/intro/shop-search/trading` — look for a normal `200`/
    `30x` response, not a `403`/`429`/Cloudflare-style challenge page or connection
    reset/timeout.
  - If `curl` looks fine but the real concern is Playwright/JS-rendering-level blocking (a bare
    `curl` can pass while a real browser still gets fingerprinted), do a quick one-off Playwright
    smoke test instead: install just `playwright` + Chromium on the VM
    (`pip install playwright && playwright install --with-deps chromium`) and run a short script
    that loads the same URL and checks for the expected catalog markup/selectors (reuse
    `playwright_provider.py`'s `SELECTORS`/`ITEM_CARD` as the success signal) — this catches
    blocking that only triggers against real browser traffic, not plain HTTP clients.
  - **If blocked**: try `terraform destroy`/`apply` again first — Oracle reassigns a new public
    IP from its pool on a fresh instance, and the specific IP (not Oracle as a provider) may be
    the flagged one. If a few fresh IPs all get blocked, treat Oracle's IP ranges as fingerprinted
    for this site and fall back to the Hetzner plan (different provider, different IP ranges) —
    re-run this same gate check on the Hetzner box before continuing there too.
- [ ] Install Docker Engine + Docker Compose plugin (Ubuntu: `apt-get install docker.io
      docker-compose-plugin`, or Docker's official convenience script).
- [ ] **Oracle-specific gotcha**: opening ports in the OCI Security List is not enough — Ubuntu's
      own `iptables`/`ufw` also blocks inbound traffic by default on Oracle's stock images. Must
      also open the relevant ports at the OS level (`ufw allow 8000`, `ufw allow 3000`, or adjust
      `iptables` directly) or services will be unreachable despite a correct Security List.
- [ ] Deliver the code (per open question #4): `git clone <repo>` or `scp -r D:\Rag
      ubuntu@<ip>:~/Rag`.
- [ ] Create `market_intel/.env` on the server from `.env.example`, with production values
      (`HEADLESS=true` stays true on a headless server; review `POLL_INTERVAL_SECONDS` and other
      throttling values are unchanged from local unless intentionally tuning).
- [ ] Edit `docker-compose.yml`'s `frontend.build.args.NEXT_PUBLIC_API_BASE_URL` to the real
      public IP (or domain, if Phase 5 is in scope first).
- [ ] If migrating existing data (open question #5): copy the local `market_intel.db` (and
      `*-wal`/`*-shm` if present, or better, cleanly stop the local collector/API first so there's
      no pending WAL data) into the `market_intel_data` Docker volume's mount point on the server
      *before* first `docker compose up`, so the `migrate` step runs against real data, not a
      fresh DB. Easiest approach: `scp` the file to the server, then `docker run --rm -v
      market_intel_data:/data -v ~/uploaded:/src alpine cp /src/market_intel.db /data/` (or
      equivalent) before starting the other services.

### Phase 4 — Go live

- [ ] `docker compose up -d --build` on the server.
- [ ] Verify: `docker compose ps` (all services up), `curl http://localhost:8000/health`,
      collector logs show a clean scrape cycle (`docker compose logs -f collector`), frontend
      loads at `http://<public-ip>:3000`.
- [ ] Resolve open question #7 (Discord vs. local sound) — switch `local_sound` off and configure
      real Discord credentials via the dashboard's Settings page if going with Discord.
- [ ] Soak-test for at least one full poll cycle + one watch-rule check cycle before considering
      this done; check `/collector/status` reflects healthy state, not stuck/offline.

### Phase 5 — Decommission the local setup

- [ ] Once the cloud instance is confirmed stable (recommend at least 24h of clean operation),
      remove the local Windows Task Scheduler tasks: `Unregister-ScheduledTask -TaskName
      "MarketIntelAll"` and `"MarketIntelRollup"` (see the
      `windows-task-scheduler-local-only` memory for full detail/rationale — this was always the
      planned end-state once a cloud version took over).
- [ ] Stop any locally-running collector/API/frontend processes still active from prior sessions.
- [ ] Decide whether to keep the local `.venv`/DB around as a backup/dev environment, or remove
      it — not urgent either way.

### Phase 6 — Optional: domain + HTTPS (only if open question #6 says yes)

- [ ] Point a domain's A record at the instance's public IP.
- [ ] Add a reverse proxy (Caddy is simplest — automatic Let's Encrypt with ~5 lines of config)
      in front of the `api` and `frontend` containers, terminating TLS.
- [ ] Update `NEXT_PUBLIC_API_BASE_URL` to the HTTPS domain and rebuild the frontend image.
- [ ] Update the OCI Security List + `ufw` to open 80/443 instead of (or in addition to) 8000/3000
      directly.

## Ongoing maintenance notes (fill in once live)

- **Deploying updates**: `git pull` (or re-`scp`) on the server, then `docker compose up -d
  --build`.
- **Backing up the SQLite file**: `<TBD — decide once live: periodic `docker cp`/cron job to pull
  the volume's file off-box, or rely on Oracle block volume backups>`.
- **Viewing logs**: `docker compose logs -f <service>`.
- **Restarting after a server reboot**: Docker's `restart: unless-stopped` policy handles
  container restart automatically once the Docker daemon comes back up; confirm the Docker daemon
  itself is enabled to start on boot (`systemctl enable docker`, usually default on Ubuntu).
