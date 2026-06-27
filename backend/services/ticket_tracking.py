"""Helpers for recording SDLC stage transactions and tracking ticket status.

Two small, reusable functions used by the webhook and the pipeline services to
keep the durable ticket history in sync:

  record_transaction()   — append an immutable StageTransaction row (the timeline).
  upsert_ticket_status()  — create/update the single TicketStatus row per ticket
                            (current coarse stage + human status + feature detail).

Both delegate to the repository layer (repositories/*) and validate inputs
defensively before writing. Callers pass the Mongo Database handle (the
request-scoped handle from get_db, or get_database() inside a background task).

Design note: these are best-effort bookkeeping. Pipeline call sites should wrap
them in try/except so a logging failure never turns a successful SDLC stage into
a failed one (matching the existing post-merge scan / QA-autochain convention).
"""

import logging

from pymongo.database import Database

from database import Doc
from models.stage_transaction import TRANSACTION_STATUSES
from models.ticket_status import VALID_STAGES
from repositories import stage_transaction_repo, ticket_status_repo

logger = logging.getLogger("backend.ticket_tracking")


def record_transaction(
    db: Database,
    project_id: int,
    ticket_key: str,
    stage: str,
    event: str,
    *,
    status: str = "success",
    result_url: str | None = None,
    detail: str | None = None,
) -> Doc:
    """Append a StageTransaction row and return it.

    Validates stage/status defensively; unknown values raise ValueError so a
    miswired call site is caught in tests rather than silently storing garbage.
    """
    if stage not in VALID_STAGES:
        raise ValueError(f"stage must be one of {sorted(VALID_STAGES)}, got {stage!r}")
    if status not in TRANSACTION_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(TRANSACTION_STATUSES)}, got {status!r}"
        )

    txn = stage_transaction_repo.append(
        db,
        project_id,
        ticket_key,
        stage,
        event,
        status=status,
        result_url=result_url,
        detail=detail,
    )
    logger.info(
        "stage transaction recorded ticket=%s stage=%s status=%s",
        ticket_key,
        stage,
        status,
    )
    return txn


def upsert_ticket_status(
    db: Database,
    project_id: int,
    ticket_key: str,
    *,
    pipeline_stage: str | None = None,
    current_status: str | None = None,
    summary: str | None = None,
    issue_type: str | None = None,
) -> Doc:
    """Create or update the single TicketStatus row for (project_id, ticket_key).

    Only fields passed (non-None) are written, so callers can update just the
    current_status without clobbering a previously stored summary. A new row
    requires a pipeline_stage; if none is supplied for a brand-new ticket it
    defaults to "description" (handled by the repository).
    """
    return ticket_status_repo.upsert(
        db,
        project_id,
        ticket_key,
        pipeline_stage=pipeline_stage,
        current_status=current_status,
        summary=summary,
        issue_type=issue_type,
    )


# ---------------------------------------------------------------------------
# Best-effort wrappers for pipeline call sites
# ---------------------------------------------------------------------------
# Pipelines must never fail because bookkeeping failed. These swallow and log
# any error, returning None.


def safe_record_transaction(db: Database, *args, **kwargs) -> Doc | None:
    """record_transaction that never raises — for use inside pipelines."""
    try:
        return record_transaction(db, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break pipelines
        logger.warning("Failed to record stage transaction: %s", exc)
        return None


def safe_upsert_ticket_status(db: Database, *args, **kwargs) -> Doc | None:
    """upsert_ticket_status that never raises — for use inside pipelines."""
    try:
        return upsert_ticket_status(db, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break pipelines
        logger.warning("Failed to upsert ticket status: %s", exc)
        return None
