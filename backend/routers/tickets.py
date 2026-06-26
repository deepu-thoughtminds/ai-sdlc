"""Ticket status & history API endpoints (JWT-protected).

Read-only views over the data populated by the SDLC pipelines:
  GET /api/projects/{project_id}/tickets
      — list every tracked ticket in a project with its current status.
  GET /api/projects/{project_id}/tickets/{ticket_key}/status
      — the current coarse stage + human status for one ticket (task 3).
  GET /api/projects/{project_id}/tickets/{ticket_key}
      — feature request details + the full chronological stage-transaction
        timeline for one ticket (task 4).

All routes require a valid JWT (same get_current_user dependency as the rest of
/api). The Jira webhook keeps its own HMAC secret and is unaffected.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from datetime import datetime
from models.project import Project
from models.stage_transaction import StageTransaction, StageTransactionPublic
from models.ticket_status import TicketStatus, TicketStatusPublic
from services.auth import get_current_user

logger = logging.getLogger("backend.tickets")

# All ticket routes require a valid JWT.
router = APIRouter(dependencies=[Depends(get_current_user)])


class TicketDetail(BaseModel):
    """Feature request details + full transaction timeline for one ticket."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_key: str
    pipeline_stage: str
    current_status: str | None = None
    summary: str | None = None
    issue_type: str | None = None
    created_at: datetime
    updated_at: datetime
    transactions: list[StageTransactionPublic]


def _get_project_or_404(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project


def _get_ticket_or_404(db: Session, project_id: int, ticket_key: str) -> TicketStatus:
    ticket = db.execute(
        select(TicketStatus).where(
            TicketStatus.project_id == project_id,
            TicketStatus.ticket_key == ticket_key,
        )
    ).scalars().first()
    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ticket {ticket_key} not found in project {project_id}",
        )
    return ticket


@router.get(
    "/projects/{project_id}/tickets",
    response_model=list[TicketStatusPublic],
)
def list_tickets(project_id: int, db: Session = Depends(get_db)) -> list[TicketStatus]:
    """List all tracked tickets in a project with their current status."""
    _get_project_or_404(db, project_id)
    rows = db.execute(
        select(TicketStatus)
        .where(TicketStatus.project_id == project_id)
        .order_by(TicketStatus.updated_at.desc())
    ).scalars().all()
    return list(rows)


@router.get(
    "/projects/{project_id}/tickets/{ticket_key}/status",
    response_model=TicketStatusPublic,
)
def get_ticket_status(
    project_id: int, ticket_key: str, db: Session = Depends(get_db)
) -> TicketStatus:
    """Return the current status of a single Jira ticket (task 3).

    404 if the project or the ticket is unknown.
    """
    _get_project_or_404(db, project_id)
    return _get_ticket_or_404(db, project_id, ticket_key)


@router.get(
    "/projects/{project_id}/tickets/{ticket_key}",
    response_model=TicketDetail,
)
def get_ticket_detail(
    project_id: int, ticket_key: str, db: Session = Depends(get_db)
) -> TicketDetail:
    """Return feature request details + the full SDLC transaction timeline (task 4).

    Transactions are returned oldest-first so the client can render the pipeline
    history in order. 404 if the project or ticket is unknown.
    """
    _get_project_or_404(db, project_id)
    ticket = _get_ticket_or_404(db, project_id, ticket_key)

    transactions = db.execute(
        select(StageTransaction)
        .where(
            StageTransaction.project_id == project_id,
            StageTransaction.ticket_key == ticket_key,
        )
        .order_by(StageTransaction.created_at, StageTransaction.id)
    ).scalars().all()

    return TicketDetail(
        id=ticket.id,
        ticket_key=ticket.ticket_key,
        pipeline_stage=ticket.pipeline_stage,
        current_status=ticket.current_status,
        summary=ticket.summary,
        issue_type=ticket.issue_type,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        transactions=[StageTransactionPublic.model_validate(t) for t in transactions],
    )
