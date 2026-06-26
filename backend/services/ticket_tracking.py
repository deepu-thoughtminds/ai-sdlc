"""Helpers for recording SDLC stage transactions and tracking ticket status.

Two small, reusable functions used by the webhook and the pipeline services to
keep the durable ticket history in sync:

  record_transaction()   — append an immutable StageTransaction row (the timeline).
  upsert_ticket_status()  — create/update the single TicketStatus row per ticket
                            (current coarse stage + human status + feature detail).

Callers pass their own SQLAlchemy session: the request-scoped session for the
inline describe flow, or the fresh SessionLocal() opened inside each background
pipeline task. Both functions commit on success.

Design note: these are best-effort bookkeeping. Pipeline call sites should wrap
them in try/except so a logging failure never turns a successful SDLC stage into
a failed one (matching the existing post-merge scan / QA-autochain convention).
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.stage_transaction import TRANSACTION_STATUSES, StageTransaction
from models.ticket_status import VALID_STAGES, TicketStatus

logger = logging.getLogger("backend.ticket_tracking")


def record_transaction(
    db: Session,
    project_id: int,
    ticket_key: str,
    stage: str,
    event: str,
    *,
    status: str = "success",
    result_url: str | None = None,
    detail: str | None = None,
) -> StageTransaction:
    """Append a StageTransaction row and commit.

    Validates stage/status defensively; unknown values raise ValueError so a
    miswired call site is caught in tests rather than silently storing garbage.
    """
    if stage not in VALID_STAGES:
        raise ValueError(f"stage must be one of {sorted(VALID_STAGES)}, got {stage!r}")
    if status not in TRANSACTION_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(TRANSACTION_STATUSES)}, got {status!r}"
        )

    txn = StageTransaction(
        project_id=project_id,
        ticket_key=ticket_key,
        stage=stage,
        event=event,
        status=status,
        result_url=result_url,
        detail=detail,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    logger.info(
        "stage transaction recorded ticket=%s stage=%s status=%s",
        ticket_key,
        stage,
        status,
    )
    return txn


def upsert_ticket_status(
    db: Session,
    project_id: int,
    ticket_key: str,
    *,
    pipeline_stage: str | None = None,
    current_status: str | None = None,
    summary: str | None = None,
    issue_type: str | None = None,
) -> TicketStatus:
    """Create or update the single TicketStatus row for (project_id, ticket_key).

    Only fields passed (non-None) are written, so callers can update just the
    current_status without clobbering a previously stored summary. A new row
    requires a pipeline_stage (the NOT NULL coarse stage); if none is supplied
    for a brand-new ticket it defaults to "description".
    """
    if pipeline_stage is not None and pipeline_stage not in VALID_STAGES:
        raise ValueError(
            f"pipeline_stage must be one of {sorted(VALID_STAGES)}, got {pipeline_stage!r}"
        )

    existing = db.execute(
        select(TicketStatus).where(
            TicketStatus.project_id == project_id,
            TicketStatus.ticket_key == ticket_key,
        )
    ).scalars().first()

    if existing is None:
        ts = TicketStatus(
            project_id=project_id,
            ticket_key=ticket_key,
            pipeline_stage=pipeline_stage or "description",
            current_status=current_status,
            summary=summary,
            issue_type=issue_type,
        )
        db.add(ts)
    else:
        ts = existing
        if pipeline_stage is not None:
            ts.pipeline_stage = pipeline_stage
        if current_status is not None:
            ts.current_status = current_status
        if summary is not None:
            ts.summary = summary
        if issue_type is not None:
            ts.issue_type = issue_type

    db.commit()
    db.refresh(ts)
    return ts


# ---------------------------------------------------------------------------
# Best-effort wrappers for pipeline call sites
# ---------------------------------------------------------------------------
# Pipelines must never fail because bookkeeping failed. These swallow and log
# any error (and roll back so the caller's session stays usable), returning None.


def safe_record_transaction(db: Session, *args, **kwargs) -> StageTransaction | None:
    """record_transaction that never raises — for use inside pipelines."""
    try:
        return record_transaction(db, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break pipelines
        logger.warning("Failed to record stage transaction: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def safe_upsert_ticket_status(db: Session, *args, **kwargs) -> TicketStatus | None:
    """upsert_ticket_status that never raises — for use inside pipelines."""
    try:
        return upsert_ticket_status(db, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — bookkeeping must not break pipelines
        logger.warning("Failed to upsert ticket status: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None
