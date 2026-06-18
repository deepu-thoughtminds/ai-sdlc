"""TDD tests for the project API endpoints.

TDD RED phase: these tests import from database, models, and routers that do not
yet exist — they will fail with ImportError until the GREEN phase implements those
modules.

Tests (8 total):
1. test_create_project_returns_201 - POST returns 201 with "id" key
2. test_create_project_response_omits_tokens - POST response has no token fields
3. test_create_project_persists_encrypted - DB row stores ciphertext, not plaintext
4. test_list_projects_empty - GET /api/projects on fresh DB returns []
5. test_list_projects_after_create - after POST, GET returns list with 1 item
6. test_get_project_by_id - GET /api/projects/{id} returns correct project_key
7. test_get_project_by_id_omits_tokens - GET by id response has no token fields
8. test_create_project_missing_required_field - missing project_key returns 422
"""

import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set ENCRYPTION_KEY before importing app modules that depend on it.
_TEST_KEY = Fernet.generate_key().decode()
os.environ["ENCRYPTION_KEY"] = _TEST_KEY

from database import Base, get_db  # noqa: E402
from main import app  # noqa: E402

# ---------------------------------------------------------------------------
# In-memory SQLite test DB setup
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)
Base.metadata.create_all(TEST_ENGINE)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)

# ---------------------------------------------------------------------------
# Shared test payload
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "name": "Test Project",
    "project_key": "TESTPROJ",
    "jira_url": "https://test.atlassian.net",
    "jira_token": "plaintext-jira-token",
    "github_token": "plaintext-github-token",
    "confluence_url": "https://test.atlassian.net/wiki",
    "confluence_token": "plaintext-confluence-token",
}

TOKEN_FIELD_NAMES = {"jira_token", "github_token", "confluence_token"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_project_returns_201() -> None:
    """POST /api/projects with full valid payload must return HTTP 201 and include 'id'."""
    response = client.post("/api/projects", json=VALID_PAYLOAD)
    assert response.status_code == 201, response.text
    data = response.json()
    assert "id" in data
    assert isinstance(data["id"], int)


def test_create_project_response_omits_tokens() -> None:
    """POST response body must NOT contain any plaintext or encrypted token fields."""
    response = client.post("/api/projects", json=VALID_PAYLOAD)
    assert response.status_code == 201, response.text
    data = response.json()
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in response"


def test_create_project_persists_encrypted() -> None:
    """After POST, the DB row must store an encrypted ciphertext, not the plaintext token."""
    response = client.post("/api/projects", json=VALID_PAYLOAD)
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    # Query the DB directly to inspect the stored token value.
    db = TestingSession()
    try:
        from models.project import Project
        row = db.get(Project, project_id)
        assert row is not None
        # Fernet ciphertext starts with "gAAAAA" (base64-encoded token version byte)
        assert row.jira_token != "plaintext-jira-token"
        assert "plaintext-jira-token" not in row.jira_token
        assert row.jira_token.startswith("gAAAAA"), (
            f"Expected Fernet ciphertext (starts with 'gAAAAA'), got: {row.jira_token[:20]}"
        )
    finally:
        db.close()


def test_list_projects_empty() -> None:
    """GET /api/projects on a fresh DB (no prior creates in this test) returns 200 and a list."""
    # Use a brand-new engine so this test is isolated
    from fastapi.testclient import TestClient as TC
    fresh_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    FreshSession = sessionmaker(bind=fresh_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(fresh_engine)

    def fresh_get_db():
        db = FreshSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = fresh_get_db
    fresh_client = TC(app)
    response = fresh_client.get("/api/projects")
    app.dependency_overrides[get_db] = override_get_db  # restore

    assert response.status_code == 200, response.text
    assert response.json() == []


def test_list_projects_after_create() -> None:
    """After POST, GET /api/projects returns a list with at least 1 item containing 'id' and 'project_key'."""
    # Use a fresh isolated DB for this test
    isolated_engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    IsolatedSession = sessionmaker(bind=isolated_engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(isolated_engine)

    def isolated_get_db():
        db = IsolatedSession()
        try:
            yield db
        finally:
            db.close()

    from fastapi.testclient import TestClient as TC
    app.dependency_overrides[get_db] = isolated_get_db
    isolated_client = TC(app)

    isolated_client.post("/api/projects", json=VALID_PAYLOAD)
    response = isolated_client.get("/api/projects")
    app.dependency_overrides[get_db] = override_get_db  # restore

    assert response.status_code == 200, response.text
    items = response.json()
    assert len(items) >= 1
    assert "id" in items[0]
    assert "project_key" in items[0]


def test_get_project_by_id() -> None:
    """POST then GET /api/projects/{id} returns 200 with the correct project_key."""
    post_response = client.post("/api/projects", json=VALID_PAYLOAD)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()
    assert data["project_key"] == VALID_PAYLOAD["project_key"]
    assert data["id"] == project_id


def test_get_project_by_id_omits_tokens() -> None:
    """GET /api/projects/{id} response must NOT contain token fields."""
    post_response = client.post("/api/projects", json=VALID_PAYLOAD)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in GET response"


def test_create_project_missing_required_field() -> None:
    """POST without required field 'project_key' must return 422 Unprocessable Entity."""
    payload_without_key = {k: v for k, v in VALID_PAYLOAD.items() if k != "project_key"}
    response = client.post("/api/projects", json=payload_without_key)
    assert response.status_code == 422, response.text
