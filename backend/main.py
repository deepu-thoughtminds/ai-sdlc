import logging
import os

from fastapi import FastAPI

from routers.webhook import router as webhook_router

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("backend")

app = FastAPI(title="AI-SDLC Jira Backend")

app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Backend started")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "backend"}
