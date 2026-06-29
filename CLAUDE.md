# Rag / market_intel — Project Instructions

## Stack
- **Python 3.12** (deadsnakes PPA), FastAPI + SQLAlchemy + Alembic, SQLite WAL
- **Node.js 20** (NodeSource), Next.js (production build via `npm run build && npm run start`)
- **Playwright** headless Chromium for scraping
- ragwatch installs individual modules (playwright_provider, discord_notifier, etc.) — **not** a `ragwatch` package. Install from repo root: `pip install -e .`

## Deployment target: AWS EC2
- Instance: t4g.small (ARM/aarch64), Ubuntu 22.04, sa-east-1, instance ID `i-068ee0908091de06e`
- **The public IP changes on every stop/start** — always look it up before SSH:
  `AWS_PROFILE=market-intel aws ec2 describe-instances --region sa-east-1 --instance-ids i-068ee0908091de06e --query "Reservations[0].Instances[0].PublicIpAddress" --output text`
- AWS credentials: use profile `market-intel` (in `~/.aws/credentials`)
- SSH: `ssh -i ~/.ssh/oracle_market_intel ubuntu@<current-ip>`
- Repo lives at `/home/ubuntu/Rag`; venv at `/home/ubuntu/Rag/.venv`
- DB at `/home/ubuntu/Rag/market_intel/market_intel.db`
- Terraform state: `D:\Rag\infra\aws\terraform.tfstate`; plugin cache: `D:\terraform-plugin-cache` (TF_PLUGIN_CACHE_DIR — C: may be full)

## Services (systemd, auto-restart)
```
market-intel-api        → uvicorn :8000
market-intel-collector  → python -m market_intel.collector.runner
market-intel-frontend   → npm run start :3000
```
Control: `sudo systemctl [start|stop|restart|status] market-intel-{api,collector,frontend}`
Logs: `sudo journalctl -u market-intel-collector -f`

## Running processes — important rules
- **Never restart services mid-scrape** — SIGTERM during Playwright closes the browser and kills all in-flight items (TargetClosedError). Wait for idle or check logs first.
- The collector sleeps 600 s between cycles. "offline" status in the frontend is cosmetic immediately after restart; it resolves after the first successful cycle.
- To force a scrape cycle, stop the service, run the runner directly, then restart the service.

## Local dev vs. AWS
- All production work targets AWS — do **not** start local Task Scheduler jobs or local services.
- Windows Task Scheduler jobs (MarketIntelAll, MarketIntelRollup) have been removed.
- `winsound` is not available on Linux — the codebase no-ops it silently.
- `NEXT_PUBLIC_API_BASE_URL` is baked at Next.js build time; rebuild frontend after changing the API host.

## SQLite / Alembic
- Always migrate all three WAL files together: `market_intel.db`, `market_intel.db-wal`, `market_intel.db-shm`
- Untracked local migration files won't be in git — check `git status` in `db/migrations/versions/` before syncing to server
- Run migrations: `cd /home/ubuntu/Rag && .venv/bin/python -m market_intel.db.init_db`

## Terraform (infra/aws/)
- Set `TF_PLUGIN_CACHE_DIR=D:\terraform-plugin-cache` before any `terraform` command if C: is low on space
- Resources: VPC, IGW, subnet (map_public_ip=true), route table, SG (22/3000/8000 ingress), key pair, EC2 t4g.small 30 GB gp3, user_data sets up 2 GB swap

## Key file locations
| What | Where |
|---|---|
| API router | `market_intel/api/routers/` |
| DB models | `market_intel/db/models.py` |
| Repository | `market_intel/db/repository.py` |
| Collector runner | `market_intel/collector/runner.py` |
| Migrations | `market_intel/db/migrations/versions/` |
| Env file (server) | `/home/ubuntu/Rag/market_intel/.env` |
| Systemd units | `/etc/systemd/system/market-intel-*.service` |
