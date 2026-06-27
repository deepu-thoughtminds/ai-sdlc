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

from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database

from database import Doc, get_db
from models.project import Project
from models.ticket_status import ProjectWithTickets, TicketStatus, TicketStatusCreate, TicketStatusPublic
from repositories import projects_repo, ticket_status_repo
from services.auth import get_current_user
from services.crypto import decrypt_credential

logger = logging.getLogger("backend.dashboard")

# All dashboard routes require a valid JWT.
router = APIRouter(dependencies=[Depends(get_current_user)])


def _project_to_with_tickets(
    project: Project, ticket_statuses: list[Doc]
) -> ProjectWithTickets:
    """Build a ProjectWithTickets response, decrypting github_repo from ciphertext.

    Constructs the response manually to ensure github_repo is decrypted.
    Token fields (jira_token, github_token, confluence_token) are excluded per T-02-08.
    T-15-02: github_repo decrypted only here — never logged, never returned as ciphertext.
    """
    statuses = [
        TicketStatusPublic(
            id=ts.id,
            ticket_key=ts.ticket_key,
            pipeline_stage=ts.pipeline_stage,
            summary=ts.get("summary"),
            issue_type=ts.get("issue_type"),
            current_status=ts.get("current_status"),
            updated_at=ts.updated_at,
        )
        for ts in ticket_statuses
    ]
    return ProjectWithTickets(
        id=project.id,
        name=project.name,
        project_key=project.project_key,
        jira_url=project.jira_url,
        confluence_url=project.confluence_url,
        github_repo=decrypt_credential(project.github_repo),
        created_at=project.created_at,
        ticket_statuses=statuses,
    )


@router.get("/dashboard/projects", response_model=list[ProjectWithTickets])
def list_projects_with_tickets(db: Database = Depends(get_db)) -> list[ProjectWithTickets]:
    """Return all projects with their nested ticket statuses.

    Fetches each project's ticket_statuses from its collection (one query per
    project). For the dev-scale dashboard this is fine; if project counts grow,
    a single grouped aggregation can replace the per-project lookup.

    Threat T-02-08: Response schema ProjectWithTickets excludes all token fields.
    T-15-02: github_repo decrypted via _project_to_with_tickets before returning.
    """
    projects = projects_repo.list_all(db)
    return [
        _project_to_with_tickets(p, ticket_status_repo.list_for_project(db, p.id))
        for p in projects
    ]


@router.post(
    "/dashboard/projects/{project_id}/tickets",
    response_model=TicketStatusPublic,
    status_code=200,
)
def upsert_ticket_status(
    project_id: int,
    body: TicketStatusCreate,
    db: Database = Depends(get_db),
) -> TicketStatus:
    """Create or update the pipeline stage for a ticket.

    Upsert logic (repositories.ticket_status_repo.upsert):
      - If a row exists for (project_id, ticket_key): update pipeline_stage + updated_at
      - If no row exists: create a new row

    Threat T-02-09: TicketStatusCreate.@field_validator rejects invalid stages (FastAPI returns 422).
    Threat T-02-10: 404 if project_id does not exist in the projects collection.
    """
    # Verify project exists (T-02-10)
    if projects_repo.get(db, project_id) is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    ts = ticket_status_repo.upsert(
        db, project_id, body.ticket_key, pipeline_stage=body.pipeline_stage
    )
    logger.info(
        "upserted ticket status project_id=%d ticket_key=%s stage=%s",
        project_id,
        body.ticket_key,
        body.pipeline_stage,
    )
    return ts
