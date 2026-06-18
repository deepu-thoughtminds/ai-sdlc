"""FastAPI router for project CRUD operations.

Endpoints:
  POST /projects  — Create a new project; tokens are encrypted before storage.
  GET  /projects  — List all projects (compact ProjectListItem schema).
  GET  /projects/{project_id} — Get single project by ID (ProjectPublic schema).

Threat mitigations:
  T-02-01: Pydantic ProjectCreate validates all fields (max_length, HttpUrl, pattern).
  T-02-02: All responses use ProjectPublic or ProjectListItem — token fields never returned.
  T-02-03: Tokens are encrypted via encrypt_credential() before ORM object creation.
  T-02-04: logger.info only logs project id, never token values.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models.project import Project, ProjectCreate, ProjectListItem, ProjectPublic
from services.crypto import encrypt_credential

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/projects", response_model=ProjectPublic, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
) -> Project:
    """Create a new project, encrypting all credential tokens before storage.

    Returns ProjectPublic (no token fields) with HTTP 201.
    T-02-04: only project id is logged — no token values.
    """
    project = Project(
        name=payload.name,
        project_key=payload.project_key,
        jira_url=str(payload.jira_url),
        jira_email=payload.jira_email,
        confluence_url=str(payload.confluence_url),
        # Encrypt tokens before writing to DB (T-02-03)
        jira_token=encrypt_credential(payload.jira_token),
        github_token=encrypt_credential(payload.github_token),
        confluence_token=encrypt_credential(payload.confluence_token),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info("project created id=%d", project.id)  # T-02-04: no token values logged
    return project


@router.get("/projects", response_model=list[ProjectListItem])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    """Return all projects as compact list items (no token fields, no URLs)."""
    return list(db.execute(select(Project)).scalars().all())


@router.get("/projects/{project_id}", response_model=ProjectPublic)
def get_project(project_id: int, db: Session = Depends(get_db)) -> Project:
    """Return a single project by ID.

    Returns ProjectPublic (no token fields) with HTTP 200.
    Returns HTTP 404 if no project with that ID exists.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return project
