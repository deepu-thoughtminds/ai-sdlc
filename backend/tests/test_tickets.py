"""Tests for the ticket status & history endpoints (routers/tickets.py).

Follows the StaticPool in-memory SQLite + dependency-override pattern from
test_dashboard.py. Auth is stubbed (these tests cover ticket reads, not auth).
"""

import os

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

from database import Base, get_db  # noqa: E402
import models.project  # noqa: E402
import models.ticket_status  # noqa: E402
import models.stage_transaction  # noqa: E402
from models.project import Project  # noqa: E402
from models.stage_transaction import StageTransaction  # noqa: E402
from models.ticket_status import TicketStatus  # noqa: E402
from main import app  # noqa: E402

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

from services.auth import get_current_user  # noqa: E402

app.dependency_overrides[get_current_user] = lambda: "test-admin"

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_tables():
    prior = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    if prior is not None:
        app.dependency_overrides[get_db] = prior
    else:
        app.dependency_overrides.pop(get_db, None)


def _seed() -> int:
    """Create a project, one ticket status, and three transactions. Returns project id."""
    db = TestingSession()
    try:
        p = Project(
            name="P", project_key="P",
            jira_url="https://x.atlassian.net", confluence_url="https://x.atlassian.net/wiki",
            jira_token="c", github_token="c", confluence_token="c", github_repo="c",
        )
        db.add(p)
        db.commit()
        db.refresh(p)

        db.add(TicketStatus(
            project_id=p.id, ticket_key="P-1", pipeline_stage="dev",
            current_status="Coding finished and PR sent",
            summary="Add login page", issue_type="Story",
        ))
        for stage, event in [
            ("description", "Generated description"),
            ("architecture", "Published to Confluence"),
            ("dev", "Coding finished and PR sent"),
        ]:
            db.add(StageTransaction(
                project_id=p.id, ticket_key="P-1", stage=stage, event=event, status="success"
            ))
        db.commit()
        return p.id
    finally:
        db.close()


def test_list_tickets() -> None:
    pid = _seed()
    resp = client.get(f"/api/projects/{pid}/tickets")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["ticket_key"] == "P-1"
    assert data[0]["current_status"] == "Coding finished and PR sent"


def test_get_ticket_status() -> None:
    pid = _seed()
    resp = client.get(f"/api/projects/{pid}/tickets/P-1/status")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["pipeline_stage"] == "dev"
    assert data["current_status"] == "Coding finished and PR sent"
    assert data["summary"] == "Add login page"
    assert data["issue_type"] == "Story"


def test_get_ticket_detail_returns_ordered_transactions() -> None:
    pid = _seed()
    resp = client.get(f"/api/projects/{pid}/tickets/P-1")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["summary"] == "Add login page"
    assert data["issue_type"] == "Story"
    stages = [t["stage"] for t in data["transactions"]]
    assert stages == ["description", "architecture", "dev"]
    # no sensitive fields leak through the transaction schema
    assert "project_id" not in data["transactions"][0]


def test_status_unknown_project_404() -> None:
    resp = client.get("/api/projects/999/tickets/P-1/status")
    assert resp.status_code == 404, resp.text


def test_status_unknown_ticket_404() -> None:
    pid = _seed()
    resp = client.get(f"/api/projects/{pid}/tickets/NOPE-1/status")
    assert resp.status_code == 404, resp.text


def test_detail_unknown_ticket_404() -> None:
    pid = _seed()
    resp = client.get(f"/api/projects/{pid}/tickets/NOPE-1")
    assert resp.status_code == 404, resp.text


def test_endpoints_require_auth() -> None:
    """With the auth override removed, the routes return 401."""
    pid = _seed()
    app.dependency_overrides.pop(get_current_user, None)
    try:
        assert client.get(f"/api/projects/{pid}/tickets").status_code == 401
        assert client.get(f"/api/projects/{pid}/tickets/P-1/status").status_code == 401
        assert client.get(f"/api/projects/{pid}/tickets/P-1").status_code == 401
    finally:
        app.dependency_overrides[get_current_user] = lambda: "test-admin"
