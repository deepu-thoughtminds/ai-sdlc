import logging
import os

from fastapi import FastAPI

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
