"""Tests for the pipeline_states collection and its Pydantic schemas.

Uses the shared mongomock fixtures in conftest.py. The repository layer
(repositories/pipeline_state_repo.py) replaces direct ORM access.
"""

from datetime import datetime

from models.pipeline_state import PipelineStateCreate, PipelineStatePublic
from repositories import pipeline_state_repo
from tests.support import make_project


def test_pipeline_state_create(db) -> None:
    """Create a row with status='pending'; id assigned and created_at set."""
    project_id = make_project(db, project_key="PIPETEST").id
    ps = pipeline_state_repo.create(
        db, project_id, "PIPETEST-1", "describe", status="pending"
    )
    assert ps.id is not None
    assert ps.id > 0
    assert ps.status == "pending"
    assert ps.ticket_key == "PIPETEST-1"
    assert ps.stage == "describe"
    assert ps.project_id == project_id
    assert isinstance(ps.created_at, datetime)


def test_pipeline_state_status_transition(db) -> None:
    """Update status pending -> processing -> awaiting_approval; change persists."""
    project_id = make_project(db, project_key="PIPETEST").id
    ps = pipeline_state_repo.create(
        db, project_id, "PIPETEST-2", "describe", status="pending"
    )
    pipeline_state_repo.update(db, ps.id, status="processing")
    pipeline_state_repo.update(db, ps.id, status="awaiting_approval")

    row = pipeline_state_repo.get(db, ps.id)
    assert row.status == "awaiting_approval"


def test_pipeline_state_draft_content_nullable(db) -> None:
    """Create with draft_content=None — no error."""
    project_id = make_project(db, project_key="PIPETEST").id
    ps = pipeline_state_repo.create(
        db, project_id, "PIPETEST-3", "describe", status="pending", draft_content=None
    )
    assert ps.id is not None
    assert ps.draft_content is None


def test_pipeline_state_multiple_runs_per_ticket_stage(db) -> None:
    """Two rows for same (project_id, ticket_key, stage) are allowed (multiple runs)."""
    project_id = make_project(db, project_key="PIPETEST").id
    pipeline_state_repo.create(db, project_id, "PIPETEST-4", "describe", status="pending")
    pipeline_state_repo.create(db, project_id, "PIPETEST-4", "describe", status="processing")

    rows = list(
        db["pipeline_states"].find(
            {"project_id": project_id, "ticket_key": "PIPETEST-4", "stage": "describe"}
        )
    )
    assert len(rows) == 2, f"Expected 2 rows (multiple runs allowed), got {len(rows)}"


# ---------------------------------------------------------------------------
# qa_attempt field
# ---------------------------------------------------------------------------


def test_qa_attempt_defaults_to_none(db) -> None:
    """Create without qa_attempt — defaults to None (not yet in QA)."""
    project_id = make_project(db, project_key="PIPETEST").id
    ps = pipeline_state_repo.create(db, project_id, "QATEST-1", "qa", status="pending")
    assert "qa_attempt" in ps
    assert ps.qa_attempt is None


def test_qa_attempt_zero_on_first_run(db) -> None:
    """qa_attempt=0 (first run started) persists."""
    project_id = make_project(db, project_key="PIPETEST").id
    ps = pipeline_state_repo.create(
        db, project_id, "QATEST-2", "qa", status="processing", qa_attempt=0
    )
    assert pipeline_state_repo.get(db, ps.id).qa_attempt == 0


def test_qa_attempt_increments(db) -> None:
    """qa_attempt updated to 2 (after two fix loops) persists."""
    project_id = make_project(db, project_key="PIPETEST").id
    ps = pipeline_state_repo.create(db, project_id, "QATEST-3", "qa", status="processing")
    pipeline_state_repo.update(db, ps.id, qa_attempt=2)
    assert pipeline_state_repo.get(db, ps.id).qa_attempt == 2


def test_pipeline_state_create_schema_has_qa_attempt() -> None:
    """PipelineStateCreate schema exposes qa_attempt defaulting to None."""
    obj = PipelineStateCreate(project_id=1, ticket_key="QATEST-4", stage="qa")
    assert hasattr(obj, "qa_attempt")
    assert obj.qa_attempt is None


def test_pipeline_state_public_schema_has_qa_attempt() -> None:
    """PipelineStatePublic.model_fields contains qa_attempt."""
    assert "qa_attempt" in PipelineStatePublic.model_fields
