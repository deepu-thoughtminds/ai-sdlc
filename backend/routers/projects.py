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

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models.pipeline_state import PipelineState
from models.project import Project, ProjectCreate, ProjectListItem, ProjectPublic, ProjectUpdate
from models.stage_transaction import StageTransaction
from services import codebase_scan_service
from services.auth import get_current_user
from services.crypto import decrypt_credential, encrypt_credential

logger = logging.getLogger(__name__)

# All project routes require a valid JWT (covers POST/GET/GET/PUT/DELETE).
router = APIRouter(dependencies=[Depends(get_current_user)])


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
async def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
) -> ProjectPublic:
    """Create a new project, encrypting all credential tokens and github_repo before storage.

    Returns ProjectPublic (no token fields, decrypted github_repo) with HTTP 201.
    T-02-04: only project id is logged — no token values.
    T-15-02: github_repo stored as ciphertext; returned decrypted via _project_to_public.
    SCAN-01: when github_repo is non-empty, schedules an async codebase scan
    background task immediately after project creation.
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

    if payload.github_repo:
        # SCAN-01: Trigger codebase scan as background task on project onboarding.
        # PipelineState committed BEFORE asyncio.create_task() so duplicate-guard
        # (Phase 19) can detect an in-flight scan. ticket_key "__onboarding__" is
        # the sentinel value used when no Jira ticket exists at onboarding time.
        scan_state = PipelineState(
            project_id=project.id,
            ticket_key="__onboarding__",
            stage="codebase_scan",
            status="running",
        )
        db.add(scan_state)
        db.commit()

        project_id = project.id

        async def _run_scan_background() -> None:
            # CR-02: Open a fresh session — never reuse the request-scoped db session.
            bg_db = SessionLocal()
            try:
                bg_project = bg_db.query(Project).filter(Project.id == project_id).first()
                if bg_project is None:
                    logger.warning(
                        "Project id=%s not found in scan background task — aborting",
                        project_id,
                    )
                    return
                github_token = decrypt_credential(bg_project.github_token)  # T-18-01: not logged
                github_repo = decrypt_credential(bg_project.github_repo)
                try:
                    await codebase_scan_service.run(github_repo, github_token, project_id, bg_db)
                except Exception as exc:
                    logger.warning(
                        "Codebase scan failed for project id=%s: %s", project_id, exc
                    )
                    # Mark PipelineState as error so UI can surface the failure
                    bg_db.query(PipelineState).filter(
                        PipelineState.project_id == project_id,
                        PipelineState.stage == "codebase_scan",
                        PipelineState.status == "running",
                    ).update({"status": "error"})
                    bg_db.commit()
            finally:
                bg_db.close()

        asyncio.create_task(_run_scan_background())
        logger.info("Codebase scan scheduled project id=%d", project.id)  # T-18-01: no token

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


@router.put("/projects/{project_id}", response_model=ProjectPublic)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
) -> ProjectPublic:
    """Update an existing project. Only provided fields are changed.

    Token and github_repo fields are re-encrypted when a non-empty value is
    supplied; omitted or empty values leave the stored ciphertext untouched
    (T-02-03). Returns ProjectPublic (no token fields). 404 if not found;
    409 if a new project_key collides with another project.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    # Only consider fields the client actually sent (exclude_unset).
    data = payload.model_dump(exclude_unset=True)

    # Plain (non-encrypted) fields — HttpUrl values must be coerced to str.
    if "name" in data and data["name"] is not None:
        project.name = data["name"]
    if "project_key" in data and data["project_key"] is not None:
        project.project_key = data["project_key"]
    if "jira_url" in data and data["jira_url"] is not None:
        project.jira_url = str(payload.jira_url)
    if "jira_email" in data and data["jira_email"] is not None:
        project.jira_email = data["jira_email"]
    if "confluence_url" in data and data["confluence_url"] is not None:
        project.confluence_url = str(payload.confluence_url)

    # Encrypted fields — re-encrypt only when a non-empty value is supplied.
    for enc_field in ("jira_token", "github_token", "confluence_token", "github_repo"):
        value = data.get(enc_field)
        if value:  # non-empty string only; empty/None means "leave unchanged"
            setattr(project, enc_field, encrypt_credential(value))

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="project_key already in use by another project",
        )
    db.refresh(project)
    logger.info("project updated id=%d", project.id)  # no token values logged
    return _project_to_public(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a project and its related rows.

    ticket_statuses are removed via the ORM relationship cascade. pipeline_states
    and stage_transactions have no ORM relationship and SQLite does not enforce FK
    cascades by default, so they are deleted explicitly here to avoid orphan rows.
    Returns 204; 404 if not found.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")
    db.query(PipelineState).filter(PipelineState.project_id == project_id).delete()
    db.query(StageTransaction).filter(StageTransaction.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    logger.info("project deleted id=%d", project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
