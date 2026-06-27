import json
import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import get_database, init_indexes
from routers.auth import router as auth_router
from routers.dashboard import router as dashboard_router
from routers.projects import router as projects_router
from routers.tickets import router as tickets_router
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

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    try:
        raw_body = await request.body()
        body_str = raw_body.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body_str)
            body_log = json.dumps(parsed, indent=2)
        except Exception:
            body_log = body_str
    except Exception as e:
        body_log = f"<could not read body: {e}>"

    logger.error(
        "422 Validation error on %s %s\nErrors: %s\nRaw body:\n%s",
        request.method,
        request.url,
        exc.errors(),
        body_log,
    )
    def _safe_errors(errors):
        result = []
        for e in errors:
            ec = dict(e)
            if "ctx" in ec and isinstance(ec["ctx"].get("error"), Exception):
                ec = dict(ec)
                ec["ctx"] = {**ec["ctx"], "error": str(ec["ctx"]["error"])}
            result.append(ec)
        return result

    return JSONResponse(status_code=422, content={"detail": _safe_errors(exc.errors())})


app.include_router(webhook_router, prefix="/webhook", tags=["webhook"])
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(projects_router, prefix="/api", tags=["projects"])
app.include_router(dashboard_router, prefix="/api", tags=["dashboard"])
app.include_router(tickets_router, prefix="/api", tags=["tickets"])


@app.on_event("startup")
async def startup_event() -> None:
    init_indexes(get_database())
    logger.info("Backend started")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "backend"}
