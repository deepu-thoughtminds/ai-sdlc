import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
import models.ticket_status  # noqa: F401 — registers TicketStatus table with Base.metadata
import models.pipeline_state  # noqa: F401 — registers PipelineState table with Base.metadata
from routers.dashboard import router as dashboard_router
from routers.projects import router as projects_router
from routers.webhook import router as webhook_router

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("backend")

app = FastAPI(title="AI-SDLC Jira Backend")

# Allow the frontend (default localhost:3000 for local dev) to call this API
# cross-origin. Without this, the browser's OPTIONS preflight for POST
# requests returns 405 and the request never reaches the route ("Failed to
# fetch" in the frontend). Origin is restricted to a single configurable
# value (never wildcard "*") since allow_credentials=True is set.
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])
app.include_router(projects_router, prefix="/api", tags=["projects"])
app.include_router(dashboard_router, prefix="/api", tags=["dashboard"])


@app.on_event("startup")
async def startup_event() -> None:
    init_db()
    logger.info("Backend started")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "backend"}
