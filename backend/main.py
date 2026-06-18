import logging
import os

from fastapi import FastAPI

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("backend")

app = FastAPI(title="AI-SDLC Jira Backend")


@app.on_event("startup")
async def startup_event() -> None:
    logger.info("Backend started")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "backend"}
