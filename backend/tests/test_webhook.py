"""Tests for POST /webhook/jira-comment endpoint.

Tests (13 total):
Existing (4, kept intact):
1. test_valid_webhook_returns_200 - returns 200 + status received (project not found → ignored is also 200/received)
2. test_missing_required_field_returns_422 - 422 on missing required field
3. test_no_mention_returns_ignored - no @jarvis mention → action=ignored
4. test_hermes_mention_returns_action - @jarvis describe with matching project → action=describe

New (4 from Phase 3):
5. test_describe_mention_creates_pipeline_state - describe → action=describe and PipelineState row created
6. test_assign_mention_calls_assign_pipeline - assign → action=assign
7. test_approval_comment_triggers_approval - LGTM comment with awaiting_approval row → action=approval_applied
8. test_unknown_project_returns_ignored - unknown project key → action=ignored, reason=project_not_found

New (2 from Phase 4-02):
9. test_architecture_mention_returns_action - @jarvis architecture → action=architecture, routed_to=freellmapi
10. test_architecture_mention_schedules_pipeline - @jarvis architecture for known project → asyncio.create_task called

New (3 from Phase 13-02): Idempotency guard
11. test_architecture_duplicate_returns_ignored - second @jarvis architecture while active PipelineState running → action=ignored, reason=duplicate_pipeline
12. test_architecture_failed_state_allows_new_run - existing PipelineState with status=failed does NOT block a new run
13. test_architecture_creates_pipeline_state_before_task - new architecture run creates PipelineState(status=running) before scheduling task

Uses StaticPool + same dependency override pattern from test_dashboard.py.
Pipeline service calls are mocked at 'routers.webhook.*' import path.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing any app modules.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# In-memory SQLite with StaticPool — all connections share the same DB.
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

from database import Base, get_db  # noqa: E402
import models.project  # noqa: E402
import models.ticket_status  # noqa: E402
import models.pipeline_state  # noqa: E402
from models.project import Project  # noqa: E402
from models.pipeline_state import PipelineState  # noqa: E402
from services.crypto import encrypt_credential  # noqa: E402
from main import app  # noqa: E402

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_tables():
    """Install webhook DB override, drop/recreate tables, restore prior override after.

    The module-level override is NOT installed at import time to avoid
    contaminating other test modules that load before test_webhook runs.
    Instead, each test installs and tears down the override via this fixture.
    """
    prior_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    if prior_override is not None:
        app.dependency_overrides[get_db] = prior_override
    else:
        app.dependency_overrides.pop(get_db, None)


def _create_project(db, key: str = "PROJ") -> Project:
    """Insert a Project row and return the ORM object."""
    project = Project(
        name="Test Project",
        project_key=key,
        jira_url="https://test.atlassian.net",
        confluence_url="https://test.atlassian.net/wiki",
        jira_token=encrypt_credential("fake-jira-token"),
        github_token=encrypt_credential("fake-github-token"),
        confluence_token=encrypt_credential("fake-confluence-token"),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Shared payloads
# ---------------------------------------------------------------------------

VALID_DESCRIBE_PAYLOAD = {
    "webhook_event": "comment_created",
    "issue": {"id": "10001", "key": "PROJ-1", "summary": "Feature X"},
    "comment": {"id": "20001", "body": "@jarvis describe", "author": "alice"},
    "timestamp": 1718000000,
}

NO_MENTION_PAYLOAD = {
    "webhook_event": "comment_created",
    "issue": {"id": "10001", "key": "PROJ-2", "summary": "Feature Y"},
    "comment": {"id": "20002", "body": "Nice work team!", "author": "bob"},
    "timestamp": 1718000001,
}

MISSING_FIELD_PAYLOAD = {
    "webhook_event": "comment_created",
    "comment": {"id": "20003", "body": "@jarvis describe", "author": "carol"},
    "timestamp": 1718000002,
}

UNKNOWN_PROJECT_PAYLOAD = {
    "webhook_event": "comment_created",
    "issue": {"id": "99999", "key": "UNKNOWN-1", "summary": "Unknown"},
    "comment": {"id": "20099", "body": "@jarvis describe", "author": "dave"},
    "timestamp": 1718000010,
}

# ---------------------------------------------------------------------------
# Existing tests (preserved, adapted for project-lookup logic)
# ---------------------------------------------------------------------------


async def test_valid_webhook_returns_200():
    """Test 1: POST with valid JiraCommentEvent returns HTTP 200 and status received.

    With no project in DB, the handler returns action=ignored (still 200 + status=received).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=VALID_DESCRIBE_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"


async def test_missing_required_field_returns_422():
    """Test 2: POST with missing required field returns HTTP 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=MISSING_FIELD_PAYLOAD)
    assert response.status_code == 422


async def test_no_mention_returns_ignored():
    """Test 3: POST where comment body has no @jarvis mention returns action: ignored.

    No project in DB for PROJ-2 → returns project_not_found ignored.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=NO_MENTION_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body.get("action") == "ignored"


async def test_hermes_mention_returns_action():
    """Test 4: POST with @jarvis describe (legacy, removed) and a matching project
    now returns action=ignored — auto-trigger on Story creation is primary.
    """
    db = TestingSession()
    try:
        _create_project(db, key="PROJ")
    finally:
        db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=VALID_DESCRIBE_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body.get("action") == "ignored"


# ---------------------------------------------------------------------------
# New integration tests (Task 2)
# ---------------------------------------------------------------------------


async def test_describe_mention_creates_pipeline_state():
    """Test 5: POST with '@jarvis describe' and matching project returns action=describe
    and creates a PipelineState row with status='awaiting_approval'.
    """
    db = TestingSession()
    try:
        project = _create_project(db, key="PROJ")
        project_id = project.id
    finally:
        db.close()

    story_created_payload = {
        "webhook_event": "jira:issue_created",
        "issue": {
            "id": "10001",
            "key": "PROJ-1",
            "summary": "Feature X",
            "issue_type": "Story",
        },
        "timestamp": 1718000000,
    }

    with patch("routers.webhook.describe_pipeline.run", new_callable=AsyncMock) as mock_run, \
         patch("routers.webhook.hermes_post_comment", new_callable=AsyncMock) as mock_post_comment, \
         patch("routers.webhook.decrypt_credential", return_value="plaintext-token"):
        mock_run.return_value = "Draft text."
        mock_post_comment.return_value = {}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-issue", json=story_created_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "describe"

    # Verify PipelineState row was created in DB
    check_db = TestingSession()
    try:
        row = (
            check_db.query(PipelineState)
            .filter(
                PipelineState.project_id == project_id,
                PipelineState.ticket_key == "PROJ-1",
                PipelineState.stage == "describe",
            )
            .first()
        )
        assert row is not None, "PipelineState row should exist"
        assert row.status == "awaiting_approval"
        assert row.draft_content == "Draft text."
    finally:
        check_db.close()


async def test_issue_created_ignores_non_story():
    """POST /webhook/jira-issue with issue_type='Bug' returns ignored/not_a_story."""
    db = TestingSession()
    try:
        _create_project(db, key="PROJ")
    finally:
        db.close()

    bug_created_payload = {
        "webhook_event": "jira:issue_created",
        "issue": {
            "id": "10002",
            "key": "PROJ-2",
            "summary": "Bug Y",
            "issue_type": "Bug",
        },
        "timestamp": 1718000001,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-issue", json=bug_created_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "ignored"
    assert body["reason"] == "not_a_story"


async def test_issue_created_duplicate_returns_ignored():
    """Second jira:issue_created for a ticket with an active describe PipelineState
    returns action=ignored, reason=duplicate_pipeline.
    """
    db = TestingSession()
    try:
        project = _create_project(db, key="PROJ")
        existing = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-3",
            stage="describe",
            status="awaiting_approval",
            draft_content="Already drafted.",
        )
        db.add(existing)
        db.commit()
    finally:
        db.close()

    story_created_payload = {
        "webhook_event": "jira:issue_created",
        "issue": {
            "id": "10003",
            "key": "PROJ-3",
            "summary": "Feature Z",
            "issue_type": "Story",
        },
        "timestamp": 1718000002,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-issue", json=story_created_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "ignored"
    assert body["reason"] == "duplicate_pipeline"


async def test_assign_mention_calls_assign_pipeline():
    """Test 6: POST with '@jarvis assign @jane.smith' returns action=assign."""
    db = TestingSession()
    try:
        _create_project(db, key="PROJ")
    finally:
        db.close()

    assign_payload = {
        "webhook_event": "comment_created",
        "issue": {"id": "10001", "key": "PROJ-1", "summary": "Feature X"},
        "comment": {"id": "20001", "body": "@jarvis assign @jane.smith", "author": "alice"},
        "timestamp": 1718000000,
    }

    with patch("routers.webhook.assign_pipeline.run", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-comment", json=assign_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "assign"
    mock_run.assert_called_once()


async def test_approval_comment_triggers_approval():
    """Test 7: POST with plain 'LGTM' comment and existing awaiting_approval row
    returns action=approval_applied.
    """
    db = TestingSession()
    try:
        project = _create_project(db, key="PROJ")

        # Insert awaiting_approval PipelineState row
        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="describe",
            status="awaiting_approval",
            draft_content="Elaborated description.",
        )
        db.add(ps)
        db.commit()
    finally:
        db.close()

    approval_payload = {
        "webhook_event": "comment_created",
        "issue": {"id": "10001", "key": "PROJ-1", "summary": "Feature X"},
        "comment": {"id": "20050", "body": "@jarvis approve story description", "author": "alice"},
        "timestamp": 1718000005,
    }

    with patch(
        "routers.webhook.approval_detector.detect_and_apply_approval",
        new_callable=AsyncMock,
    ) as mock_detect:
        mock_detect.return_value = True

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-comment", json=approval_payload)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "approval_applied"
    mock_detect.assert_called_once()


async def test_unknown_project_returns_ignored():
    """Test 8: POST with issue key 'UNKNOWN-1' where no project with key 'UNKNOWN'
    exists in DB returns action=ignored and reason=project_not_found.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=UNKNOWN_PROJECT_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "ignored"
    assert body.get("reason") == "project_not_found"


# ---------------------------------------------------------------------------
# New tests (Phase 04-02): architecture routing
# ---------------------------------------------------------------------------


ARCHITECTURE_PAYLOAD = {
    "webhook_event": "comment_created",
    "issue": {"id": "10001", "key": "PROJ-1", "summary": "New feature"},
    "comment": {"id": "20001", "body": "@jarvis architecture", "author": "architect"},
    "timestamp": 1718000020,
}


async def test_architecture_mention_returns_action():
    """Test 9: POST with '@jarvis architecture' and a matching project returns
    status=received, action=architecture, routed_to=freellmapi.
    """
    db = TestingSession()
    try:
        _create_project(db, key="PROJ")
    finally:
        db.close()

    # Patch asyncio.create_task to prevent real background coroutine from running.
    # Patch architecture_pipeline.run to return a completed coroutine (not AsyncMock,
    # which creates unawaited coroutine warnings when create_task is also mocked).
    with patch("routers.webhook.asyncio.create_task") as mock_create_task:
        mock_create_task.return_value = None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-comment", json=ARCHITECTURE_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["action"] == "architecture"
    assert body["routed_to"] == "freellmapi"


async def test_architecture_mention_schedules_pipeline():
    """Test 10: POST with '@jarvis architecture' for a known project calls
    asyncio.create_task once to schedule architecture_pipeline.run.
    """
    db = TestingSession()
    try:
        _create_project(db, key="PROJ")
    finally:
        db.close()

    # Patch asyncio.create_task to prevent background execution in test context.
    # asyncio.create_task receives a coroutine from architecture_pipeline.run();
    # we close it immediately to avoid "coroutine was never awaited" warnings.
    captured_coros: list = []

    def _capture_and_close(coro):
        captured_coros.append(coro)
        coro.close()  # prevent "never awaited" ResourceWarning
        return None

    with patch("routers.webhook.asyncio.create_task", side_effect=_capture_and_close):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-comment", json=ARCHITECTURE_PAYLOAD)

    assert response.status_code == 200
    # asyncio.create_task should have been called exactly once
    assert len(captured_coros) == 1


# ---------------------------------------------------------------------------
# New test (Quick 260618-n0u): real Jira Cloud / Jira Automation payload shape
# ---------------------------------------------------------------------------


NATIVE_JIRA_PAYLOAD = {
    "webhookEvent": "comment_created",
    "issue": {
        "id": "10001",
        "key": "PROJ-1",
        "fields": {"summary": "Native shaped issue", "description": "Plain text description"},
    },
    "comment": {
        "id": "30001",
        "body": "Just a plain comment, no mention",
        "author": {"accountId": "acc-123", "displayName": "Alice Architect"},
    },
    "timestamp": 1718000030,
}


async def test_native_jira_shaped_payload_returns_200():
    """Real Jira Cloud / Jira Automation 'issue data' payload shape (webhookEvent,
    issue.fields.summary, comment.author object) must return 200, not 422.
    """
    db = TestingSession()
    try:
        _create_project(db, key="PROJ")
    finally:
        db.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=NATIVE_JIRA_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"


# ---------------------------------------------------------------------------
# New tests (Phase 13-02): Idempotency guard for architecture branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_architecture_duplicate_returns_ignored():
    """Test 11: Second @jarvis architecture webhook for PROJ-1 while a PipelineState row
    with stage='architecture' and status='running' exists → returns reason=duplicate_pipeline
    with HTTP 200; asyncio.create_task is NOT called.
    """
    db = TestingSession()
    try:
        project = _create_project(db, key="PROJ")
        # Pre-insert an active (running) PipelineState row
        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="architecture",
            status="running",
        )
        db.add(ps)
        db.commit()
    finally:
        db.close()

    captured_coros: list = []

    def _capture_and_close(coro):
        captured_coros.append(coro)
        coro.close()
        return None

    with patch("routers.webhook.asyncio.create_task", side_effect=_capture_and_close):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-comment", json=ARCHITECTURE_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["action"] == "ignored"
    assert body["reason"] == "duplicate_pipeline"
    # asyncio.create_task must NOT have been called
    assert len(captured_coros) == 0


@pytest.mark.asyncio
async def test_architecture_failed_state_allows_new_run():
    """Test 12: Existing PipelineState with status='failed' does NOT block a new run.
    asyncio.create_task IS called.
    """
    db = TestingSession()
    try:
        project = _create_project(db, key="PROJ")
        # Pre-insert a FAILED PipelineState row — must not block new run
        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="architecture",
            status="failed",
        )
        db.add(ps)
        db.commit()
    finally:
        db.close()

    captured_coros: list = []

    def _capture_and_close(coro):
        captured_coros.append(coro)
        coro.close()
        return None

    with patch("routers.webhook.asyncio.create_task", side_effect=_capture_and_close):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-comment", json=ARCHITECTURE_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "architecture"
    # asyncio.create_task should have been called once (new run allowed)
    assert len(captured_coros) == 1


@pytest.mark.asyncio
async def test_architecture_creates_pipeline_state_before_task():
    """Test 13: New architecture run creates a PipelineState row with status='running'
    committed BEFORE asyncio.create_task is called.
    """
    db = TestingSession()
    try:
        project = _create_project(db, key="PROJ")
        project_id = project.id
    finally:
        db.close()

    pipeline_state_seen_in_db: list = []

    def _check_db_then_close(coro):
        # At the moment create_task is called, the PipelineState row must already be in DB
        check_db = TestingSession()
        try:
            row = check_db.query(PipelineState).filter(
                PipelineState.ticket_key == "PROJ-1",
                PipelineState.stage == "architecture",
                PipelineState.status == "running",
            ).first()
            pipeline_state_seen_in_db.append(row)
        finally:
            check_db.close()
        coro.close()
        return None

    with patch("routers.webhook.asyncio.create_task", side_effect=_check_db_then_close):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/webhook/jira-comment", json=ARCHITECTURE_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["action"] == "architecture"
    # Exactly one PipelineState row must have been found at create_task call time
    assert len(pipeline_state_seen_in_db) == 1
    assert pipeline_state_seen_in_db[0] is not None
