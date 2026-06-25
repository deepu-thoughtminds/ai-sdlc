"""Tests for services/ticket_tracking.py (record_transaction + upsert_ticket_status).

Follows the StaticPool in-memory SQLite pattern from test_pipeline_state.py.
"""

import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

from database import Base  # noqa: E402
import models.project  # noqa: E402
import models.ticket_status  # noqa: E402
import models.stage_transaction  # noqa: E402
from models.project import Project  # noqa: E402
from models.stage_transaction import StageTransaction  # noqa: E402
from models.ticket_status import TicketStatus  # noqa: E402
from services.ticket_tracking import (  # noqa: E402
    record_transaction,
    safe_record_transaction,
    safe_upsert_ticket_status,
    upsert_ticket_status,
)

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def reset_tables():
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)


def _make_project(db) -> Project:
    p = Project(
        name="P", project_key="P",
        jira_url="https://x.atlassian.net", confluence_url="https://x.atlassian.net/wiki",
        jira_token="c", github_token="c", confluence_token="c", github_repo="c",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_record_transaction_appends_rows() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        record_transaction(db, p.id, "P-1", "description", "Generated description")
        record_transaction(db, p.id, "P-1", "dev", "PR sent", result_url="http://pr/1")

        rows = db.execute(
            select(StageTransaction).where(StageTransaction.ticket_key == "P-1")
        ).scalars().all()
        assert len(rows) == 2
        assert {r.stage for r in rows} == {"description", "dev"}
    finally:
        db.close()


def test_record_transaction_rejects_bad_stage_and_status() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        with pytest.raises(ValueError):
            record_transaction(db, p.id, "P-1", "bogus", "x")
        with pytest.raises(ValueError):
            record_transaction(db, p.id, "P-1", "dev", "x", status="bogus")
    finally:
        db.close()


def test_upsert_creates_then_updates_single_row() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        upsert_ticket_status(
            db, p.id, "P-1",
            pipeline_stage="description", current_status="Ticket created",
            summary="Add login", issue_type="Story",
        )
        # Second call updates the same row (no duplicate).
        upsert_ticket_status(
            db, p.id, "P-1", pipeline_stage="dev", current_status="Coding started",
        )

        rows = db.execute(
            select(TicketStatus).where(TicketStatus.ticket_key == "P-1")
        ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.pipeline_stage == "dev"
        assert row.current_status == "Coding started"
        # summary/issue_type preserved from the first call (not clobbered)
        assert row.summary == "Add login"
        assert row.issue_type == "Story"
    finally:
        db.close()


def test_upsert_rejects_bad_stage() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        with pytest.raises(ValueError):
            upsert_ticket_status(db, p.id, "P-1", pipeline_stage="bogus")
    finally:
        db.close()


def test_safe_wrappers_swallow_errors() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        # Bad stage would raise in the non-safe variant; safe variant returns None.
        assert safe_record_transaction(db, p.id, "P-1", "bogus", "x") is None
        assert safe_upsert_ticket_status(db, p.id, "P-1", pipeline_stage="bogus") is None
        # A subsequent valid call still works (session usable after rollback).
        assert safe_record_transaction(db, p.id, "P-1", "dev", "ok") is not None
    finally:
        db.close()
