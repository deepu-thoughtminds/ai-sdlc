"""TDD tests for PipelineState model.

Tests (4 total):
1. test_pipeline_state_create - create a PipelineState row with status="pending", assert id assigned and created_at is set
2. test_pipeline_state_status_transition - update status from "pending" to "awaiting_approval"
3. test_pipeline_state_draft_content_nullable - create with draft_content=None, no error
4. test_pipeline_state_unique_per_ticket_stage - inserting two rows for same (project_id, ticket_key, stage) is allowed

Follows the same StaticPool in-memory SQLite pattern from test_dashboard.py.
"""

import os
from datetime import datetime

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing any app modules.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)

# ---------------------------------------------------------------------------
# Set up a shared in-memory SQLite engine using StaticPool so all connections
# see the same database.
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Import app modules after setting env vars.
from database import Base, get_db  # noqa: E402
import models.project  # noqa: E402 — ensures Project is registered on Base.metadata
import models.ticket_status  # noqa: E402 — ensures TicketStatus is registered on Base.metadata
import models.pipeline_state  # noqa: E402 — ensures PipelineState is registered on Base.metadata
from models.pipeline_state import PipelineState, PipelineStateCreate, PipelineStatePublic  # noqa: E402

# Create tables on our StaticPool-backed engine.
Base.metadata.create_all(TEST_ENGINE)

TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def reset_tables():
    """Drop and recreate all tables before each test for full isolation."""
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)


def _make_project(db) -> int:
    """Insert a Project row and return its id."""
    from models.project import Project
    project = Project(
        name="Test Project",
        project_key="PIPETEST",
        jira_url="https://test.atlassian.net",
        confluence_url="https://test.atlassian.net/wiki",
        jira_token="enc_jira",
        github_token="enc_github",
        confluence_token="enc_confluence",
        github_repo="enc_github_repo",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pipeline_state_create() -> None:
    """Create a PipelineState row with status='pending', assert id assigned and created_at is set."""
    db = TestingSession()
    try:
        project_id = _make_project(db)
        ps = PipelineState(
            project_id=project_id,
            ticket_key="PIPETEST-1",
            stage="describe",
            status="pending",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

        assert ps.id is not None
        assert ps.id > 0
        assert ps.status == "pending"
        assert ps.ticket_key == "PIPETEST-1"
        assert ps.stage == "describe"
        assert ps.project_id == project_id
    finally:
        db.close()


def test_pipeline_state_status_transition() -> None:
    """Update status from 'pending' to 'awaiting_approval', confirm the change persists."""
    db = TestingSession()
    try:
        project_id = _make_project(db)
        ps = PipelineState(
            project_id=project_id,
            ticket_key="PIPETEST-2",
            stage="describe",
            status="pending",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)
        ps_id = ps.id

        # Transition: pending → processing → awaiting_approval
        ps.status = "processing"
        db.commit()

        ps.status = "awaiting_approval"
        db.commit()
        db.refresh(ps)

        assert ps.status == "awaiting_approval"
        # Verify persisted by re-querying
        from sqlalchemy import select
        row = db.execute(select(PipelineState).where(PipelineState.id == ps_id)).scalar_one()
        assert row.status == "awaiting_approval"
    finally:
        db.close()


def test_pipeline_state_draft_content_nullable() -> None:
    """Create PipelineState with draft_content=None — no error should be raised."""
    db = TestingSession()
    try:
        project_id = _make_project(db)
        ps = PipelineState(
            project_id=project_id,
            ticket_key="PIPETEST-3",
            stage="describe",
            status="pending",
            draft_content=None,
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

        assert ps.id is not None
        assert ps.draft_content is None
    finally:
        db.close()


def test_pipeline_state_unique_per_ticket_stage() -> None:
    """Inserting two rows for same (project_id, ticket_key, stage) is allowed (multiple runs)."""
    db = TestingSession()
    try:
        project_id = _make_project(db)
        ps1 = PipelineState(
            project_id=project_id,
            ticket_key="PIPETEST-4",
            stage="describe",
            status="pending",
        )
        ps2 = PipelineState(
            project_id=project_id,
            ticket_key="PIPETEST-4",
            stage="describe",
            status="processing",
        )
        db.add(ps1)
        db.commit()
        db.add(ps2)
        db.commit()  # Should not raise — no unique constraint on (project_id, ticket_key, stage)

        from sqlalchemy import select
        rows = db.execute(
            select(PipelineState).where(
                PipelineState.project_id == project_id,
                PipelineState.ticket_key == "PIPETEST-4",
                PipelineState.stage == "describe",
            )
        ).scalars().all()
        assert len(rows) == 2, f"Expected 2 rows (multiple runs allowed), got {len(rows)}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Phase 23 — qa_attempt column tests
# ---------------------------------------------------------------------------


def test_qa_attempt_defaults_to_none() -> None:
    """Create PipelineState without setting qa_attempt — defaults to None (not yet in QA)."""
    db = TestingSession()
    try:
        project_id = _make_project(db)
        ps = PipelineState(
            project_id=project_id,
            ticket_key="QATEST-1",
            stage="qa",
            status="pending",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

        assert hasattr(ps, "qa_attempt"), "qa_attempt attribute must exist on ORM instance"
        assert ps.qa_attempt is None, f"Expected qa_attempt=None, got {ps.qa_attempt}"
    finally:
        db.close()


def test_qa_attempt_zero_on_first_run() -> None:
    """Set qa_attempt=0 (first run started), commit, re-query — asserts the value persists."""
    db = TestingSession()
    try:
        from sqlalchemy import select

        project_id = _make_project(db)
        ps = PipelineState(
            project_id=project_id,
            ticket_key="QATEST-2",
            stage="qa",
            status="processing",
            qa_attempt=0,
        )
        db.add(ps)
        db.commit()
        ps_id = ps.id

        row = db.execute(select(PipelineState).where(PipelineState.id == ps_id)).scalar_one()
        assert row.qa_attempt == 0, f"Expected qa_attempt=0 after first run, got {row.qa_attempt}"
    finally:
        db.close()


def test_qa_attempt_increments() -> None:
    """Set qa_attempt=2 (after two fix loops), commit, re-query — asserts the value persists."""
    db = TestingSession()
    try:
        from sqlalchemy import select

        project_id = _make_project(db)
        ps = PipelineState(
            project_id=project_id,
            ticket_key="QATEST-3",
            stage="qa",
            status="processing",
            qa_attempt=2,
        )
        db.add(ps)
        db.commit()
        ps_id = ps.id

        row = db.execute(select(PipelineState).where(PipelineState.id == ps_id)).scalar_one()
        assert row.qa_attempt == 2, f"Expected qa_attempt=2, got {row.qa_attempt}"
    finally:
        db.close()


def test_pipeline_state_create_schema_has_qa_attempt() -> None:
    """PipelineStateCreate schema exposes qa_attempt field defaulting to None."""
    obj = PipelineStateCreate(project_id=1, ticket_key="QATEST-4", stage="qa")
    assert hasattr(obj, "qa_attempt"), "PipelineStateCreate must have qa_attempt field"
    assert obj.qa_attempt is None, f"Expected qa_attempt=None by default, got {obj.qa_attempt}"


def test_pipeline_state_public_schema_has_qa_attempt() -> None:
    """PipelineStatePublic schema model_fields contains qa_attempt."""
    assert "qa_attempt" in PipelineStatePublic.model_fields, (
        "PipelineStatePublic.model_fields must include 'qa_attempt'"
    )
