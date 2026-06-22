"""TDD tests for architecture_pipeline.run() — single-pass complexity-aware pipeline.

Tests (7 total):
1. test_run_complex_path — classify_complexity returns "complex"; generate_diagram called;
   publish_architecture called with is_complex=True; result contains "Multi-component feature"
2. test_run_simple_path — classify_complexity returns "small"; generate_diagram NOT called;
   publish_architecture called with is_complex=False; result contains "Simple change"
3. test_run_draft_content_is_human_readable — PipelineState.draft_content is a plain string,
   not JSON, does not start with "{"
4. test_run_creates_pipeline_state_complete — PipelineState status="complete" after run()
5. test_run_graceful_on_confluence_failure — Confluence raises; pipeline still returns string;
   no "https://conf" in result
6. test_run_calls_llm_with_architecture_stage — route_request called with stage="architecture"
   and issue_summary in prompt
7. test_run_posts_jira_comment — hermes_post_comment is called with the architecture comment body

Uses StaticPool in-memory DB; unittest.mock.patch for LLM, classify_complexity, drawio,
Confluence, and hermes_post_comment dependencies.

Threat T-04-01: prompt must not contain token values — verified by checking args to route_request.
"""

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE any app module imports.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# In-memory SQLite DB with StaticPool (all connections share same DB).
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

from database import Base  # noqa: E402
import models.project  # noqa: E402
import models.ticket_status  # noqa: E402
import models.pipeline_state  # noqa: E402
from models.project import Project  # noqa: E402
from models.pipeline_state import PipelineState  # noqa: E402
from services.crypto import encrypt_credential  # noqa: E402

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def reset_tables():
    """Drop and recreate all tables before each test for full isolation."""
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_project():
    """Return a mock Project with all fields needed by architecture_pipeline.run()."""
    p = MagicMock()
    p.id = 1
    p.project_key = "PROJ"
    p.jira_url = "https://jira.example.com"
    p.jira_token = encrypt_credential("jira-secret-token")
    p.confluence_url = "https://confluence.example.com"
    p.confluence_token = encrypt_credential("conf-secret-token")
    p.github_repo = encrypt_credential("acme/my-app")
    p.github_token = encrypt_credential("ghp-test-token")
    return p


def _make_stub_llm_response_complex():
    """Return a mock LLMResponse with 6 sections for the complex-ticket path."""
    from services.llm_router import LLMResponse
    content = (
        "## Summary\n"
        "This is a complex multi-service architecture.\n"
        "## Approach\n"
        "Use microservices with async messaging.\n"
        "## Component Breakdown\n"
        "API Gateway, Auth Service, User Service\n"
        "## Integration Points\n"
        "REST between gateway and services; Kafka for events\n"
        "## Key Decisions\n"
        "Use event sourcing for audit trail\n"
        "## Risks\n"
        "High coupling between services if not decoupled properly"
    )
    return LLMResponse(provider="freellmapi", content=content, model="llama3")


def _make_stub_llm_response_simple():
    """Return a mock LLMResponse with 4 sections for the simple-ticket path."""
    from services.llm_router import LLMResponse
    content = (
        "## Summary\n"
        "Simple single-service change.\n"
        "## Approach\n"
        "Add a field to the existing User model.\n"
        "## Key Decisions\n"
        "Minimal change — no new services needed\n"
        "## Risks\n"
        "Low risk; backward compatible"
    )
    return LLMResponse(provider="freellmapi", content=content, model="llama3")


def _make_db():
    """Return an in-memory SQLite DB session."""
    return TestingSession()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_complex_path():
    """classify_complexity returns 'complex': generate_diagram called once,
    publish_architecture called with is_complex=True, result contains
    'Multi-component feature — diagram included'.
    """
    db = _make_db()
    try:
        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("complex", "touches 3 services"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="# Codebase snapshot\nbackend/services/architecture_pipeline.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_complex(),
            ),
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ) as mock_generate_diagram,
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1",
            ) as mock_publish,
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            result = await run(
                _make_mock_project(), "PROJ-1", "Auth feature", "User can login", db
            )

        assert isinstance(result, str)
        assert "Multi-component feature — diagram included" in result
        mock_generate_diagram.assert_called_once()
        # publish_architecture must be called with is_complex=True
        call_kwargs = mock_publish.call_args[1] if mock_publish.call_args[1] else {}
        call_args = mock_publish.call_args[0] if mock_publish.call_args[0] else ()
        assert call_kwargs.get("is_complex") is True or (
            len(call_args) > 6 and call_args[6] is True
        )
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_simple_path():
    """classify_complexity returns 'small': generate_diagram NOT called,
    publish_architecture called with is_complex=False, result contains
    'Simple change — text architecture'.
    """
    db = _make_db()
    try:
        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("small", "single service change"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="# Codebase snapshot\nbackend/services/architecture_pipeline.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_simple(),
            ),
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ) as mock_generate_diagram,
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1",
            ) as mock_publish,
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            result = await run(
                _make_mock_project(), "PROJ-1", "Add field", "Add email field to User", db
            )

        assert isinstance(result, str)
        assert "Simple change — text architecture" in result
        mock_generate_diagram.assert_not_called()
        # publish_architecture must be called with is_complex=False
        call_kwargs = mock_publish.call_args[1] if mock_publish.call_args[1] else {}
        call_args = mock_publish.call_args[0] if mock_publish.call_args[0] else ()
        assert call_kwargs.get("is_complex") is False or (
            len(call_args) > 6 and call_args[6] is False
        )
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_draft_content_is_human_readable():
    """After run(), PipelineState.draft_content is a plain string — not JSON,
    does not start with '{'.
    """
    db = _make_db()
    try:
        # Insert a real Project row for FK integrity.
        project_row = Project(
            name="Test Project",
            project_key="PROJ",
            jira_url="https://jira.example.com",
            confluence_url="https://confluence.example.com",
            jira_token=encrypt_credential("jira-token"),
            github_token=encrypt_credential("github-token"),
            confluence_token=encrypt_credential("conf-token"),
            github_repo=encrypt_credential("acme/my-app"),
        )
        db.add(project_row)
        db.commit()
        db.refresh(project_row)

        mock_project = _make_mock_project()
        mock_project.id = project_row.id

        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("small", "single service"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="# Codebase snapshot\nbackend/services/architecture_pipeline.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_simple(),
            ),
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ),
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1",
            ),
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            await run(mock_project, "PROJ-1", "Simple fix", "Fix null pointer", db)

        row = (
            db.query(PipelineState)
            .filter(
                PipelineState.ticket_key == "PROJ-1",
                PipelineState.stage == "architecture",
            )
            .first()
        )
        assert row is not None
        assert row.draft_content is not None
        content = row.draft_content
        assert not content.strip().startswith("{"), "draft_content must not be JSON"
        try:
            json.loads(content)
            raise AssertionError("draft_content must not be valid JSON")
        except (json.JSONDecodeError, ValueError):
            pass  # expected — content is plain text
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_creates_pipeline_state_complete():
    """After run() completes, PipelineState has stage='architecture'
    and status='complete' (not 'awaiting_approval').
    """
    db = _make_db()
    try:
        project_row = Project(
            name="Test Project",
            project_key="PROJ",
            jira_url="https://jira.example.com",
            confluence_url="https://confluence.example.com",
            jira_token=encrypt_credential("jira-token"),
            github_token=encrypt_credential("github-token"),
            confluence_token=encrypt_credential("conf-token"),
            github_repo=encrypt_credential("acme/my-app"),
        )
        db.add(project_row)
        db.commit()
        db.refresh(project_row)

        mock_project = _make_mock_project()
        mock_project.id = project_row.id

        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("complex", "multi-service"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="# Codebase snapshot\nbackend/services/architecture_pipeline.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_complex(),
            ),
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ),
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1",
            ),
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            await run(mock_project, "PROJ-1", "Big feature", "Needs many services", db)

        rows = (
            db.query(PipelineState)
            .filter(
                PipelineState.ticket_key == "PROJ-1",
                PipelineState.stage == "architecture",
            )
            .all()
        )
        assert len(rows) >= 1
        assert rows[0].status == "complete", f"Expected 'complete', got '{rows[0].status}'"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_graceful_on_confluence_failure():
    """When Confluence publish raises an exception, run() still returns non-empty string
    and 'https://conf' is not in the result (graceful degradation — T-04-03).
    """
    db = _make_db()
    try:
        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("complex", "multi-service"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="# Codebase snapshot\nbackend/services/architecture_pipeline.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_complex(),
            ),
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ),
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                side_effect=Exception("network error"),
            ),
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            result = await run(
                _make_mock_project(), "PROJ-1", "Big feature", "Needs services", db
            )

        assert isinstance(result, str)
        assert len(result) > 0, "run() must return non-empty string even on Confluence failure"
        assert "https://conf" not in result, "Confluence URL must not appear when publishing failed"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_calls_llm_with_architecture_stage():
    """route_request is called with 'architecture' as first arg and issue_summary in prompt.

    Threat T-04-01: prompt must not contain token values.
    """
    db = _make_db()
    try:
        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("small", "single service"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="# Codebase snapshot\nbackend/services/architecture_pipeline.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_simple(),
            ) as mock_route,
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ),
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            await run(
                _make_mock_project(), "PROJ-1", "Auth feature", "User can login", db
            )

        assert mock_route.called, "route_request must be called"
        call_args = mock_route.call_args[0]
        # First positional arg must be "architecture"
        assert call_args[0] == "architecture", (
            f"Expected first arg 'architecture', got '{call_args[0]}'"
        )
        # Prompt (second arg) must contain the issue summary
        assert "Auth feature" in call_args[1], (
            "issue_summary must appear in LLM prompt"
        )
        # T-04-01: prompt must NOT contain token values
        prompt = call_args[1]
        assert "jira-secret-token" not in prompt
        assert "conf-secret-token" not in prompt
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_posts_jira_comment():
    """hermes_post_comment is called once with the architecture comment body.

    Verifies CR-01: run() must actually post the result to Jira, not merely
    return it. The 5th positional arg (body) must contain the issue key.
    """
    db = _make_db()
    try:
        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("small", "simple"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="# Codebase snapshot\nbackend/services/architecture_pipeline.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_simple(),
            ),
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ),
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ) as mock_post,
        ):
            from services.architecture_pipeline import run
            await run(_make_mock_project(), "PROJ-1", "Fix", "Small fix", db)

        mock_post.assert_called_once()
        call_body = mock_post.call_args[0][4]  # 5th positional arg is the comment body
        assert "PROJ-1" in call_body, "comment body must reference the issue key"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_includes_snapshot_in_architecture_prompt():
    """ARCHCTX-02: the codebase snapshot fetched in run() must appear in the
    architecture generation prompt passed to route_request.
    """
    db = _make_db()
    try:
        with (
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("small", "single service"),
            ),
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="SENTINEL_COMPONENT: backend/services/my_unique_module.py",
            ),
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_simple(),
            ) as mock_rr,
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ),
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            await run(_make_mock_project(), "PROJ-1", "Fix", "desc", db)

        prompt = mock_rr.call_args[0][1]
        assert "my_unique_module.py" in prompt
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_passes_snapshot_to_complexity_classifier():
    """ARCHCTX-01: the snapshot fetched in run() must be passed to
    classify_complexity() as the codebase_snapshot keyword argument.
    """
    db = _make_db()
    try:
        with (
            patch(
                "services.architecture_pipeline.get_codebase_snapshot",
                new_callable=AsyncMock,
                return_value="snapshot-content-xyz",
            ),
            patch(
                "services.architecture_pipeline.classify_complexity",
                return_value=("small", "one service"),
            ) as mock_classify,
            patch(
                "services.architecture_pipeline.route_request",
                return_value=_make_stub_llm_response_simple(),
            ),
            patch(
                "services.architecture_pipeline.generate_diagram",
                return_value="<mxGraphModel/>",
            ),
            patch(
                "services.architecture_pipeline.generate_viewer_url",
                return_value="https://diagrams.net/view",
            ),
            patch(
                "services.architecture_pipeline.publish_architecture",
                new_callable=AsyncMock,
                return_value="",
            ),
            patch(
                "services.architecture_pipeline.hermes_post_comment",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            from services.architecture_pipeline import run

            await run(_make_mock_project(), "PROJ-1", "Fix", "desc", db)

        assert mock_classify.call_args[1].get("codebase_snapshot") == "snapshot-content-xyz" or (
            mock_classify.call_args[0][-1] == "snapshot-content-xyz"
        )
    finally:
        db.close()
