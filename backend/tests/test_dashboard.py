"""Tests for the dashboard API endpoints (MongoDB-backed).

Uses the shared mongomock fixtures in conftest.py.
"""

from fastapi.testclient import TestClient

from database import get_database
from main import app
from repositories import ticket_status_repo

client = TestClient(app)

TOKEN_FIELD_NAMES = {"jira_token", "github_token", "confluence_token"}


def _create_project(key: str = "TESTPROJ", github_repo: str = "acme/my-app") -> dict:
    """Create a project via POST /api/projects and return the response JSON."""
    resp = client.post(
        "/api/projects",
        json={
            "name": "Test",
            "project_key": key,
            "jira_url": "https://x.atlassian.net",
            "jira_email": "test@example.com",
            "jira_token": "t",
            "github_token": "g",
            "confluence_url": "https://x.atlassian.net/wiki",
            "confluence_token": "c",
            "github_repo": github_repo,
        },
    )
    assert resp.status_code == 201, f"_create_project failed: {resp.text}"
    return resp.json()


def test_dashboard_projects_empty() -> None:
    response = client.get("/api/dashboard/projects")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_dashboard_projects_lists_onboarded() -> None:
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
    project = _create_project("DUPPROJ")
    project_id = project["id"]

    resp1 = client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "DUPPROJ-1", "pipeline_stage": "description"},
    )
    assert resp1.status_code == 200, resp1.text
    ticket_id_first = resp1.json()["id"]

    resp2 = client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "DUPPROJ-1", "pipeline_stage": "architecture"},
    )
    assert resp2.status_code == 200, resp2.text
    data2 = resp2.json()
    assert data2["pipeline_stage"] == "architecture"
    # Same row was updated — same id
    assert data2["id"] == ticket_id_first

    # Confirm only one row for this ticket_key + project_id
    rows = ticket_status_repo.list_for_project(get_database(), project_id)
    rows = [r for r in rows if r.ticket_key == "DUPPROJ-1"]
    assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"


def test_upsert_ticket_invalid_stage() -> None:
    project = _create_project("INVALIDSTAGE")
    project_id = project["id"]

    response = client.post(
        f"/api/dashboard/projects/{project_id}/tickets",
        json={"ticket_key": "INVALIDSTAGE-1", "pipeline_stage": "unknown"},
    )
    assert response.status_code == 422, response.text


def test_dashboard_projects_shows_ticket_statuses() -> None:
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
    response = client.post(
        "/api/dashboard/projects/9999/tickets",
        json={"ticket_key": "NOPROJECT-1", "pipeline_stage": "description"},
    )
    assert response.status_code == 404, response.text


def test_dashboard_projects_includes_github_repo() -> None:
    _create_project("GITHUBREPOPROJ", github_repo="acme/my-app")

    response = client.get("/api/dashboard/projects")
    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data) >= 1
    item = data[0]
    assert item.get("github_repo") == "acme/my-app", (
        f"Expected decrypted 'acme/my-app', got: {item.get('github_repo')!r}"
    )
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in item, (
            f"Token field '{token_field}' found in dashboard response"
        )
