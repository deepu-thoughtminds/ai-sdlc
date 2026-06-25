"""Dashboard API endpoints.

Endpoints:
  GET  /dashboard/projects                     — list all projects with nested ticket statuses
  POST /dashboard/projects/{project_id}/tickets — upsert a ticket's pipeline stage

Threat mitigations applied:
  T-02-08: Response schema is ProjectWithTickets which excludes all token fields
  T-02-09: TicketStatusCreate.@field_validator rejects invalid pipeline_stage (422 returned)
  T-02-10: db.get(Project, project_id) check before upsert — 404 if project not found
  T-15-02: github_repo decrypted at response-construction time; never returned as ciphertext
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from database import get_db
from models.project import Project
from models.ticket_status import ProjectWithTickets, TicketStatus, TicketStatusCreate, TicketStatusPublic
from services.auth import get_current_user
from services.crypto import decrypt_credential

logger = logging.getLogger("backend.dashboard")

# All dashboard routes require a valid JWT.
router = APIRouter(dependencies=[Depends(get_current_user)])


def _project_to_with_tickets(project: Project) -> ProjectWithTickets:
    """Build a ProjectWithTickets response, decrypting github_repo from ciphertext.

    Constructs the response manually to ensure github_repo is decrypted.
    Token fields (jira_token, github_token, confluence_token) are excluded per T-02-08.
    T-15-02: github_repo decrypted only here — never logged, never returned as ciphertext.
    """
    ticket_statuses = [
        TicketStatusPublic(
            id=ts.id,
            ticket_key=ts.ticket_key,
            pipeline_stage=ts.pipeline_stage,
            updated_at=ts.updated_at,
        )
        for ts in project.ticket_statuses
    ]
    return ProjectWithTickets(
        id=project.id,
        name=project.name,
        project_key=project.project_key,
        jira_url=project.jira_url,
        confluence_url=project.confluence_url,
        github_repo=decrypt_credential(project.github_repo),
        created_at=project.created_at,
        ticket_statuses=ticket_statuses,
    )


@router.get("/dashboard/projects", response_model=list[ProjectWithTickets])
def list_projects_with_tickets(db: Session = Depends(get_db)) -> list[ProjectWithTickets]:
    """Return all projects with their nested ticket statuses.

    Uses selectinload to eagerly load ticket_statuses in a single extra query,
    avoiding N+1 queries when there are many projects.

    Threat T-02-08: Response schema ProjectWithTickets excludes all token fields.
    T-15-02: github_repo decrypted via _project_to_with_tickets before returning.
    """
    stmt = select(Project).options(selectinload(Project.ticket_statuses))
    projects = db.execute(stmt).scalars().all()
    return [_project_to_with_tickets(p) for p in projects]


@router.post(
    "/dashboard/projects/{project_id}/tickets",
    response_model=TicketStatusPublic,
    status_code=200,
)
def upsert_ticket_status(
    project_id: int,
    body: TicketStatusCreate,
    db: Session = Depends(get_db),
) -> TicketStatus:
    """Create or update the pipeline stage for a ticket.

    Upsert logic:
      - If a TicketStatus row exists for (project_id, ticket_key): update pipeline_stage + updated_at
      - If no row exists: create a new TicketStatus row

    Threat T-02-09: TicketStatusCreate.@field_validator rejects invalid stages (FastAPI returns 422).
    Threat T-02-10: 404 if project_id does not exist in the projects table.
    """
    # Verify project exists (T-02-10)
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # Upsert: check for existing row
    existing = db.execute(
        select(TicketStatus).where(
            TicketStatus.project_id == project_id,
            TicketStatus.ticket_key == body.ticket_key,
        )
    ).scalars().first()

    if existing is not None:
        # Update existing row
        existing.pipeline_stage = body.pipeline_stage
        existing.updated_at = datetime.now(tz=timezone.utc)
        ts = existing
    else:
        # Create new row
        ts = TicketStatus(
            project_id=project_id,
            ticket_key=body.ticket_key,
            pipeline_stage=body.pipeline_stage,
        )
        db.add(ts)

    db.commit()
    db.refresh(ts)
    logger.info(
        "upserted ticket status project_id=%d ticket_key=%s stage=%s",
        project_id,
        body.ticket_key,
        body.pipeline_stage,
    )
    return ts
