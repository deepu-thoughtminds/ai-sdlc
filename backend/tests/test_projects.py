"""TDD tests for the project API endpoints.

Tests (11 total):
1. test_create_project_returns_201 - POST returns 201 with "id" key
2. test_create_project_response_omits_tokens - POST response has no token fields
3. test_create_project_persists_encrypted - DB row stores ciphertext, not plaintext
4. test_list_projects_empty - GET /api/projects on fresh DB returns []
5. test_list_projects_after_create - after POST, GET returns list with 1 item
6. test_get_project_by_id - GET /api/projects/{id} returns correct project_key
7. test_get_project_by_id_omits_tokens - GET by id response has no token fields
8. test_create_project_missing_required_field - missing project_key returns 422
9. test_create_project_includes_github_repo - POST response includes decrypted github_repo
10. test_create_project_github_repo_persists_encrypted - DB row stores github_repo as Fernet ciphertext
11. test_get_project_includes_github_repo - GET /api/projects/{id} returns decrypted github_repo

Implementation note on SQLite in-memory and connection pools:
SQLAlchemy's default pool creates multiple connections; each `sqlite:///:memory:`
connection gets a separate, empty database. To share state across connections we
use `StaticPool` which forces all connections through the same underlying
sqlite3 connection object, keeping the in-memory database alive and consistent.
"""

import os

import pytest
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

# Override DATABASE_URL so that database.py's module-level engine creation
# also uses in-memory SQLite (it will be a different engine object, but we
# override get_db to use TestingSession which is bound to TEST_ENGINE).
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

client = TestClient(app)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TOKEN_FIELD_NAMES = {"jira_token", "github_token", "confluence_token"}

_project_counter = 0


@pytest.fixture(autouse=True)
def reset_tables():
    """Drop and recreate all tables before each test for full isolation.

    Also re-registers this module's override_get_db for the duration of
    each test, then restores the prior override. This prevents cross-test
    contamination when test_dashboard.py or other test modules install their
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


def _unique_payload() -> dict:
    """Return a valid payload with a unique project_key to avoid UNIQUE constraint violations."""
    global _project_counter
    _project_counter += 1
    return {
        "name": f"Test Project {_project_counter}",
        "project_key": f"TESTPROJ{_project_counter}",
        "jira_url": "https://test.atlassian.net",
        "jira_email": "test@example.com",
        "jira_token": "plaintext-jira-token",
        "github_token": "plaintext-github-token",
        "confluence_url": "https://test.atlassian.net/wiki",
        "confluence_token": "plaintext-confluence-token",
        "github_repo": "acme/my-app",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_project_returns_201() -> None:
    """POST /api/projects with full valid payload must return HTTP 201 and include 'id'."""
    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text
    data = response.json()
    assert "id" in data
    assert isinstance(data["id"], int)


def test_create_project_response_omits_tokens() -> None:
    """POST response body must NOT contain any token fields."""
    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text
    data = response.json()
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in response"


def test_create_project_persists_encrypted() -> None:
    """After POST, the DB row must store Fernet ciphertext, not the plaintext token."""
    payload = _unique_payload()
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    # Query the DB directly to inspect the stored token value.
    db = TestingSession()
    try:
        from models.project import Project
        row = db.get(Project, project_id)
        assert row is not None
        stored_token = row.jira_token
        assert stored_token != payload["jira_token"], "Token must not be stored as plaintext"
        assert payload["jira_token"] not in stored_token
        # Fernet ciphertext always starts with "gAAAAA" (base64-encoded version byte)
        assert stored_token.startswith("gAAAAA"), (
            f"Expected Fernet ciphertext (starts with 'gAAAAA'), got: {stored_token[:20]!r}"
        )
    finally:
        db.close()


def test_list_projects_empty() -> None:
    """GET /api/projects on a fresh isolated DB returns 200 and an empty list."""
    # Use a separate StaticPool engine so this test has a clean slate.
    fresh_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(fresh_engine)
    FreshSession = sessionmaker(bind=fresh_engine, autocommit=False, autoflush=False)

    def fresh_get_db():
        db = FreshSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = fresh_get_db
    from fastapi.testclient import TestClient as TC
    fresh_client = TC(app)
    response = fresh_client.get("/api/projects")
    app.dependency_overrides[get_db] = override_get_db  # restore

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_list_projects_after_create() -> None:
    """After POST, GET /api/projects returns a list containing 'id' and 'project_key'."""
    payload = _unique_payload()
    create_resp = client.post("/api/projects", json=payload)
    assert create_resp.status_code == 201, create_resp.text

    list_resp = client.get("/api/projects")
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()
    assert len(items) >= 1
    assert "id" in items[0]
    assert "project_key" in items[0]


def test_get_project_by_id() -> None:
    """POST then GET /api/projects/{id} returns 200 with the correct project_key."""
    payload = _unique_payload()
    post_response = client.post("/api/projects", json=payload)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()
    assert data["project_key"] == payload["project_key"]
    assert data["id"] == project_id


def test_get_project_by_id_omits_tokens() -> None:
    """GET /api/projects/{id} response must NOT contain token fields."""
    payload = _unique_payload()
    post_response = client.post("/api/projects", json=payload)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in GET response"


def test_create_project_missing_required_field() -> None:
    """POST without required field 'project_key' must return 422 Unprocessable Entity."""
    payload = _unique_payload()
    del payload["project_key"]
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422, response.text


def test_create_project_includes_github_repo() -> None:
    """POST /api/projects response body must include decrypted github_repo (GITHUBCFG-02)."""
    payload = _unique_payload()
    payload["github_repo"] = "acme/my-app"
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert "github_repo" in data, "github_repo missing from POST response"
    assert data["github_repo"] == "acme/my-app", (
        f"Expected decrypted 'acme/my-app', got: {data['github_repo']!r}"
    )


def test_create_project_github_repo_persists_encrypted() -> None:
    """After POST, the DB row must store github_repo as Fernet ciphertext (GITHUBCFG-01)."""
    payload = _unique_payload()
    payload["github_repo"] = "acme/my-app"
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    db = TestingSession()
    try:
        from models.project import Project
        row = db.get(Project, project_id)
        assert row is not None
        stored_repo = row.github_repo
        assert stored_repo != "acme/my-app", "github_repo must not be stored as plaintext"
        assert "acme/my-app" not in stored_repo
        # Fernet ciphertext always starts with "gAAAAA"
        assert stored_repo.startswith("gAAAAA"), (
            f"Expected Fernet ciphertext (starts with 'gAAAAA'), got: {stored_repo[:20]!r}"
        )
    finally:
        db.close()


def test_create_project_missing_github_repo_returns_422() -> None:
    """POST without required field 'github_repo' must return 422 Unprocessable Entity."""
    payload = _unique_payload()
    del payload["github_repo"]
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422, response.text


def test_get_project_includes_github_repo() -> None:
    """GET /api/projects/{id} response must include decrypted github_repo (GITHUBCFG-02)."""
    payload = _unique_payload()
    payload["github_repo"] = "acme/my-app"
    post_response = client.post("/api/projects", json=payload)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()
    assert "github_repo" in data, "github_repo missing from GET response"
    assert data["github_repo"] == "acme/my-app", (
        f"Expected decrypted 'acme/my-app', got: {data['github_repo']!r}"
    )
    # Token fields must still be excluded
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in GET response"


def test_create_project_with_github_repo_commits_pipeline_state() -> None:
    """POST /api/projects with non-empty github_repo must commit a PipelineState row
    with stage='codebase_scan', status='running', ticket_key='__onboarding__' (SCAN-01)."""
    from models.pipeline_state import PipelineState

    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    db = TestingSession()
    try:
        row = (
            db.query(PipelineState)
            .filter(
                PipelineState.project_id == project_id,
                PipelineState.stage == "codebase_scan",
            )
            .first()
        )
        assert row is not None, "PipelineState row not created for codebase_scan stage"
        assert row.status == "running"
        assert row.ticket_key == "__onboarding__"
    finally:
        db.close()


def test_create_project_with_github_repo_schedules_scan_run(monkeypatch) -> None:
    """POST /api/projects with non-empty github_repo must schedule the background scan
    via asyncio.create_task (SCAN-01 asyncio.create_task trigger wiring)."""
    import asyncio as asyncio_mod

    scheduled = []

    def _fake_create_task(coro, **kwargs):
        scheduled.append(coro.cr_code.co_name)
        coro.close()  # prevent "coroutine was never awaited" ResourceWarning
        return object()  # return value is unused by create_project

    monkeypatch.setattr(asyncio_mod, "create_task", _fake_create_task)

    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text

    assert len(scheduled) == 1, (
        f"Expected asyncio.create_task called once, got {len(scheduled)} call(s)"
    )
    assert scheduled[0] == "_run_scan_background", (
        f"Expected background coroutine '_run_scan_background', got '{scheduled[0]}'"
    )
