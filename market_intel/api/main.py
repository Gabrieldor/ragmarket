import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from api.routers import (  # noqa: E402
    admin,
    analytics,
    items,
    map_aliases,
    my_sales,
    notifications,
    observations,
    scraper_config,
    sold_out,
    status,
)

app = FastAPI(title="Ragnarok Market Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(admin.router)
app.include_router(items.router)
app.include_router(observations.router)
app.include_router(analytics.router)
app.include_router(status.router)
app.include_router(my_sales.router)
app.include_router(sold_out.router)
app.include_router(notifications.router)
app.include_router(map_aliases.router)
app.include_router(scraper_config.router)


@app.get("/health")
def health():
    return {"status": "ok"}
