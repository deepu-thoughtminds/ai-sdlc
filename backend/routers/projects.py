"""FastAPI router for project CRUD operations.

Endpoints:
  POST /projects  — Create a new project; tokens and github_repo are encrypted before storage.
  GET  /projects  — List all projects (compact ProjectListItem schema).
  GET  /projects/{project_id} — Get single project by ID (ProjectPublic schema).

Threat mitigations:
  T-02-01: Pydantic ProjectCreate validates all fields (max_length, HttpUrl, pattern).
  T-02-02: All responses use ProjectPublic or ProjectListItem — token fields never returned.
  T-02-03: Tokens and github_repo are encrypted via encrypt_credential() before ORM object creation.
  T-02-04: logger.info only logs project id, never token values.
  T-15-01: github_repo pattern validated by ProjectCreate (owner/repo slug shape).
  T-15-02: github_repo decrypted at response-construction time via decrypt_credential(); never logged.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from models.project import Project, ProjectCreate, ProjectListItem, ProjectPublic
from services.crypto import decrypt_credential, encrypt_credential

logger = logging.getLogger(__name__)

router = APIRouter()


def _project_to_public(project: Project) -> ProjectPublic:
    """Build a ProjectPublic response, decrypting github_repo from ciphertext.

    Constructs the response manually rather than relying on from_attributes
    auto-serialization to ensure github_repo is decrypted before being returned.
    Token fields (jira_token, github_token, confluence_token) are not included
    in ProjectPublic per T-02-02.

    T-15-02: github_repo decrypted only here — never logged, never returned raw.
    """
    return ProjectPublic(
        id=project.id,
        name=project.name,
        project_key=project.project_key,
        jira_url=project.jira_url,
        confluence_url=project.confluence_url,
        github_repo=decrypt_credential(project.github_repo),
        created_at=project.created_at,
    )


@router.post("/projects", response_model=ProjectPublic, status_code=201)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
) -> ProjectPublic:
    """Create a new project, encrypting all credential tokens and github_repo before storage.

    Returns ProjectPublic (no token fields, decrypted github_repo) with HTTP 201.
    T-02-04: only project id is logged — no token values.
    T-15-02: github_repo stored as ciphertext; returned decrypted via _project_to_public.
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
        # Encrypt github_repo before writing to DB (GITHUBCFG-01 / T-15-02)
        github_repo=encrypt_credential(payload.github_repo),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    logger.info("project created id=%d", project.id)  # T-02-04: no token values logged
    return _project_to_public(project)


@router.get("/projects", response_model=list[ProjectListItem])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    """Return all projects as compact list items (no token fields, no URLs)."""
    return list(db.execute(select(Project)).scalars().all())


@router.get("/projects/{project_id}", response_model=ProjectPublic)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectPublic:
    """Return a single project by ID.

    Returns ProjectPublic (no token fields, decrypted github_repo) with HTTP 200.
    Returns HTTP 404 if no project with that ID exists.
    T-15-02: github_repo decrypted at response-construction time via _project_to_public.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    return _project_to_public(project)
