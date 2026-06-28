"""Tests for the ticket status & history endpoints (routers/tickets.py).

Uses the shared mongomock fixtures in conftest.py. Auth is stubbed there; one
test removes the stub to assert the routes require auth.
"""

from fastapi.testclient import TestClient

from database import get_database
from main import app
from repositories import stage_transaction_repo, ticket_status_repo
from services.auth import get_current_user
from tests.support import make_project

client = TestClient(app)


def _seed() -> int:
    """Create a project, one ticket status, and three transactions. Returns project id."""
    db = get_database()
    p = make_project(db)
    ticket_status_repo.upsert(
        db, p.id, "P-1", pipeline_stage="dev",
        current_status="Coding finished and PR sent",
        summary="Add login page", issue_type="Story",
    )
    for stage, event in [
        ("description", "Generated description"),
        ("architecture", "Published to Confluence"),
        ("dev", "Coding finished and PR sent"),
    ]:
        stage_transaction_repo.append(db, p.id, "P-1", stage, event, status="success")
    return p.id


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
