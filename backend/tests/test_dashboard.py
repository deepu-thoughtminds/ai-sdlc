"""TDD tests for the dashboard API endpoints.

Tests (8 total):
1. test_dashboard_projects_empty - GET /api/dashboard/projects on fresh DB returns []
2. test_dashboard_projects_lists_onboarded - after creating project, returns it with ticket_statuses
3. test_dashboard_projects_no_tokens - response items must NOT contain token fields
4. test_upsert_ticket_creates_new - POST /api/dashboard/projects/{id}/tickets creates new row
5. test_upsert_ticket_updates_existing - POST same ticket_key twice → updates stage (upsert)
6. test_upsert_ticket_invalid_stage - POST with pipeline_stage="unknown" returns 422
7. test_dashboard_projects_shows_ticket_statuses - GET returns project with nested ticket_statuses
8. test_upsert_ticket_unknown_project - POST to non-existent project_id returns 404

Follows the same StaticPool in-memory SQLite pattern from test_projects.py.
"""

import os

from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing any app modules.
_TEST_KEY = Fernet.generate_key().decode()
os.environ["ENCRYPTION_KEY"] = _TEST_KEY

# ---------------------------------------------------------------------------
# Set up a shared in-memory SQLite engine using StaticPool so all connections
# (app handler thread + test code) see the same database.
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
from main import app  # noqa: E402

# Create tables on our StaticPool-backed engine.
Base.metadata.create_all(TEST_ENGINE)

TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

from fastapi.testclient import TestClient  # noqa: E402
import pytest  # noqa: E402

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOKEN_FIELD_NAMES = {"jira_token", "github_token", "confluence_token"}


@pytest.fixture(autouse=True)
def reset_tables():
    """Drop and recreate all tables before each test for full isolation.

    Also re-registers the dashboard's override_get_db for the duration of
    each test, then restores the prior override. This prevents cross-test
    contamination when test_projects.py or other test modules install their
    own dependency overrides (test collection order is not guaranteed).
    """
    prior_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    # Restore the prior override (or remove ours if there was none)
    if prior_override is not None:
        app.dependency_overrides[get_db] = prior_override
    else:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_project(key: str = "TESTPROJ") -> dict:
    """Create a project via POST /api/projects and return the response JSON."""
    resp = client.post(
        "/api/projects",
        json={
            "name": "Test",
            "project_key": key,
            "jira_url": "https://x.atlassian.net",
            "jira_token": "t",
            "github_token": "g",
            "confluence_url": "https://x.atlassian.net/wiki",
            "confluence_token": "c",
        },
    )
    assert resp.status_code == 201, f"_create_project failed: {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_dashboard_projects_empty() -> None:
    """GET /api/dashboard/projects on fresh DB returns 200 and empty list."""
    response = client.get("/api/dashboard/projects")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_dashboard_projects_lists_onboarded() -> None:
    """After creating a project, GET /api/dashboard/projects returns it with ticket_statuses."""
    project = _create_project("PROJLIST")

    response = client.get("/api/dashboard/projects")
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 1
    item = data[0]
    assert item["id"] == project["id"]
    assert item["name"] == "Test"
    assert item["project_key"] == "PROJLIST"
    assert "ticket_statuses" in item
    assert item["ticket_statuses"] == []


def test_dashboard_projects_no_tokens() -> None:
    """GET /api/dashboard/projects response items must NOT contain token fields."""
    _create_project("NOTOKENPROJ")

    response = client.get("/api/dashboard/projects")
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) >= 1
    for item in data:
        for token_field in TOKEN_FIELD_NAMES:
            assert token_field not in item, (
                f"Token field '{token_field}' found in dashboard response"
            )


def test_upsert_ticket_creates_new() -> None:
    """POST /api/dashboard/projects/{id}/tickets creates a new ticket status row."""
    project = _create_project("UPSERTPROJ")
    project_id = project["id"]

    response = client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "UPSERTPROJ-1", "pipeline_stage": "description"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ticket_key"] == "UPSERTPROJ-1"
    assert data["pipeline_stage"] == "description"
    assert "id" in data
    assert "updated_at" in data


def test_upsert_ticket_updates_existing() -> None:
    """POST same ticket_key twice with different stages — second call updates stage; one row."""
    project = _create_project("DUPPROJ")
    project_id = project["id"]

    # First upsert — create
    resp1 = client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "DUPPROJ-1", "pipeline_stage": "description"},
    )
    assert resp1.status_code == 200, resp1.text
    ticket_id_first = resp1.json()["id"]

    # Second upsert — update stage
    resp2 = client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "DUPPROJ-1", "pipeline_stage": "architecture"},
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2["pipeline_stage"] == "architecture"
    # Same row was updated — same id
    assert data2["id"] == ticket_id_first

    # Confirm only one row in DB for this ticket_key + project_id
    db = TestingSession()
    try:
        from models.ticket_status import TicketStatus
        from sqlalchemy import select
        rows = db.execute(
            select(TicketStatus).where(
                TicketStatus.project_id == project_id,
                TicketStatus.ticket_key == "DUPPROJ-1",
            )
        ).scalars().all()
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
    finally:
        db.close()


def test_upsert_ticket_invalid_stage() -> None:
    """POST with pipeline_stage='unknown' returns 422 Unprocessable Entity."""
    project = _create_project("INVALIDSTAGE")
    project_id = project["id"]

    response = client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "INVALIDSTAGE-1", "pipeline_stage": "unknown"},
    )
    assert response.status_code == 422, response.text


def test_dashboard_projects_shows_ticket_statuses() -> None:
    """After upserting a ticket, GET /api/dashboard/projects shows it nested under the project."""
    project = _create_project("SHOWTICKETS")
    project_id = project["id"]

    client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "SHOWTICKETS-1", "pipeline_stage": "dev"},
    )

    response = client.get("/api/dashboard/projects")
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) == 1
    project_data = data[0]
    assert len(project_data["ticket_statuses"]) == 1
    ts = project_data["ticket_statuses"][0]
    assert ts["ticket_key"] == "SHOWTICKETS-1"
    assert ts["pipeline_stage"] == "dev"


def test_upsert_ticket_unknown_project() -> None:
    """POST /api/dashboard/projects/9999/tickets returns 404 for non-existent project."""
    response = client.post(
        "/api/dashboard/projects/9999/tickets",
        json={"ticket_key": "NOPROJECT-1", "pipeline_stage": "description"},
    )
    assert response.status_code == 404, response.text
