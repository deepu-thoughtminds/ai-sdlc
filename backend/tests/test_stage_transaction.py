"""Tests for the StageTransaction model and its Pydantic schemas.

Follows the StaticPool in-memory SQLite pattern from test_pipeline_state.py.
"""

import os
from datetime import datetime

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing any app modules.
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

from database import Base  # noqa: E402
import models.project  # noqa: E402 — registers Project
import models.ticket_status  # noqa: E402 — registers TicketStatus
import models.stage_transaction  # noqa: E402 — registers StageTransaction
from models.project import Project  # noqa: E402
from models.stage_transaction import (  # noqa: E402
    StageTransaction,
    StageTransactionCreate,
    StageTransactionPublic,
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
        name="P",
        project_key="P",
        jira_url="https://x.atlassian.net",
        confluence_url="https://x.atlassian.net/wiki",
        jira_token="c",
        github_token="c",
        confluence_token="c",
        github_repo="c",
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_stage_transaction_create_and_read() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        txn = StageTransaction(
            project_id=p.id,
            ticket_key="P-1",
            stage="dev",
            event="Coding finished and PR sent",
            status="success",
            result_url="https://github.com/acme/x/pull/3",
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)
        assert isinstance(txn.id, int)
        assert isinstance(txn.created_at, datetime)
        assert txn.result_url.endswith("/pull/3")
        assert txn.detail is None
    finally:
        db.close()


def test_multiple_transactions_ordered_by_created_at() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        for stage, event in [
            ("description", "Generated description"),
            ("architecture", "Published to Confluence"),
            ("dev", "PR sent"),
        ]:
            db.add(StageTransaction(
                project_id=p.id, ticket_key="P-1", stage=stage, event=event, status="success"
            ))
            db.commit()

        rows = db.execute(
            select(StageTransaction)
            .where(StageTransaction.ticket_key == "P-1")
            .order_by(StageTransaction.created_at, StageTransaction.id)
        ).scalars().all()
        assert [r.stage for r in rows] == ["description", "architecture", "dev"]
    finally:
        db.close()


def test_public_schema_round_trip() -> None:
    db = TestingSession()
    try:
        p = _make_project(db)
        txn = StageTransaction(
            project_id=p.id, ticket_key="P-1", stage="merge", event="PR merged", status="success"
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)
        pub = StageTransactionPublic.model_validate(txn)
        assert pub.stage == "merge"
        assert pub.event == "PR merged"
        # project_id is internal and not exposed in the public schema
        assert not hasattr(pub, "project_id")
    finally:
        db.close()


def test_create_schema_rejects_invalid_stage() -> None:
    with pytest.raises(ValueError):
        StageTransactionCreate(ticket_key="P-1", stage="bogus", event="x")


def test_create_schema_rejects_invalid_status() -> None:
    with pytest.raises(ValueError):
        StageTransactionCreate(ticket_key="P-1", stage="dev", event="x", status="bogus")
