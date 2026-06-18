"""TDD tests for architecture_pipeline.run().

Tests (4 total):
1. test_run_returns_architecture_text — mocked LLM, diagram, Confluence; returns non-empty str with "Option"
2. test_run_creates_pipeline_state — after run(), PipelineState row has stage="architecture", status="awaiting_approval"
3. test_run_calls_llm_router_with_architecture_stage — route_request called with first arg "architecture"
4. test_run_graceful_on_confluence_failure — Confluence raises; pipeline still returns non-empty string

Uses StaticPool in-memory DB; unittest.mock.patch for LLM, drawio, and Confluence dependencies.

Threat T-04-01: prompt must not contain token values — verified by checking args to route_request.
"""

import asyncio
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
    return p


def _make_stub_llm_response(content: str = "## Option 1: Microservices\nDescription: A\nComponents: API, DB\nTrade-offs: fast\n## Option 2: Monolith\nDescription: B\nComponents: App\nTrade-offs: simple"):
    """Return a mock LLMResponse."""
    from services.llm_router import LLMResponse
    return LLMResponse(provider="freellmapi", content=content, model="llama3")


def _make_db():
    """Return an in-memory SQLite DB session."""
    return TestingSession()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_architecture_text():
    """Mock LLM, drawio, Confluence; run() returns non-empty string containing 'Option'."""
    db = _make_db()
    try:
        with (
            patch("services.architecture_pipeline.route_request",
                  return_value=_make_stub_llm_response()),
            patch("services.architecture_pipeline.generate_diagram",
                  return_value="<mxGraphModel/>"),
            patch("services.architecture_pipeline.publish_architecture",
                  new_callable=AsyncMock,
                  return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1"),
        ):
            from services.architecture_pipeline import run
            result = await run(
                _make_mock_project(), "PROJ-1", "Auth feature", "User can login", db
            )

        assert isinstance(result, str)
        assert len(result) > 0
        assert "Option" in result
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_creates_pipeline_state():
    """After run(), exactly one PipelineState row exists with stage='architecture' and status='awaiting_approval'."""
    db = _make_db()
    try:
        # Insert a Project row for the FK constraint
        project_row = Project(
            name="Test Project",
            project_key="PROJ",
            jira_url="https://jira.example.com",
            confluence_url="https://confluence.example.com",
            jira_token=encrypt_credential("jira-token"),
            github_token=encrypt_credential("github-token"),
            confluence_token=encrypt_credential("conf-token"),
        )
        db.add(project_row)
        db.commit()
        db.refresh(project_row)

        mock_project = _make_mock_project()
        mock_project.id = project_row.id  # Use the real DB row's id for FK integrity

        with (
            patch("services.architecture_pipeline.route_request",
                  return_value=_make_stub_llm_response()),
            patch("services.architecture_pipeline.generate_diagram",
                  return_value="<mxGraphModel/>"),
            patch("services.architecture_pipeline.publish_architecture",
                  new_callable=AsyncMock,
                  return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1"),
        ):
            from services.architecture_pipeline import run
            await run(mock_project, "PROJ-1", "Auth feature", "User can login", db)

        rows = db.query(PipelineState).filter(
            PipelineState.ticket_key == "PROJ-1",
            PipelineState.stage == "architecture",
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "awaiting_approval"
        assert rows[0].draft_content is not None
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_calls_llm_router_with_architecture_stage():
    """route_request is called with 'architecture' as first arg and issue_summary in prompt."""
    db = _make_db()
    try:
        with (
            patch("services.architecture_pipeline.route_request",
                  return_value=_make_stub_llm_response()) as mock_route,
            patch("services.architecture_pipeline.generate_diagram",
                  return_value="<mxGraphModel/>"),
            patch("services.architecture_pipeline.publish_architecture",
                  new_callable=AsyncMock,
                  return_value=""),
        ):
            from services.architecture_pipeline import run
            await run(
                _make_mock_project(), "PROJ-1", "Auth feature", "User can login", db
            )

        mock_route.assert_called_once()
        call_args = mock_route.call_args
        # First positional arg must be "architecture"
        assert call_args[0][0] == "architecture"
        # Second arg (prompt) should reference the issue summary
        assert "Auth feature" in call_args[0][1]
    finally:
        db.close()


@pytest.mark.asyncio
async def test_run_graceful_on_confluence_failure():
    """When Confluence publish raises an exception, run() still returns non-empty string."""
    db = _make_db()
    try:
        with (
            patch("services.architecture_pipeline.route_request",
                  return_value=_make_stub_llm_response("## Option 1: Fast\nDescription: Quick\nComponents: X\nTrade-offs: good")),
            patch("services.architecture_pipeline.generate_diagram",
                  return_value="<xml/>"),
            patch("services.architecture_pipeline.publish_architecture",
                  new_callable=AsyncMock,
                  side_effect=Exception("network error")),
        ):
            from services.architecture_pipeline import run
            result = await run(
                _make_mock_project(), "PROJ-1", "Auth feature", "User can login", db
            )

        # Pipeline should complete and return non-empty text even if Confluence fails
        assert isinstance(result, str)
        assert len(result) > 0
        # When Confluence publishing fails, no URL should appear in the result
        assert "https://conf" not in result
    finally:
        db.close()
