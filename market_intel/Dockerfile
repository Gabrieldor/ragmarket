# Shared image for the API and collector services -- same Python deps, different
# command (set per-service in docker-compose.yml).
#
# Build context MUST be the repo root (D:\Rag), not market_intel/, since this needs the
# sibling `ragwatch` package (D:\Rag\src) as an editable dependency -- exactly mirroring
# the local dev setup's `pip install -e D:\Rag` step (see market_intel/README.md).
FROM python:3.12-slim

WORKDIR /app

# 1. Install the existing scraper (ragwatch) as an editable package first. market_intel's
#    own pyproject.toml only declares "ragwatch" by name (no path) -- it relies on this
#    already being importable in the environment, same as the local dev install order.
COPY pyproject.toml /app/ragwatch-src/pyproject.toml
COPY src /app/ragwatch-src/src
RUN pip install --no-cache-dir -e /app/ragwatch-src

# 2. Install market_intel's own dependencies + the Playwright browser binary. Kept as a
#    separate layer from the app code copy below so editing source files doesn't bust
#    this slow layer's Docker cache on every rebuild.
COPY market_intel/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir -e /app \
    && python -m playwright install --with-deps chromium

# 3. Now the actual application code.
COPY market_intel /app

ENV PYTHONUNBUFFERED=1
