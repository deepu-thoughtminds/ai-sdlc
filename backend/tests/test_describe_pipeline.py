"""TDD tests for describe_pipeline.run().

Tests (3 total):
1. test_run_returns_generated_description - mocked dependencies; run() returns LLM content string
2. test_run_with_no_sprint_backlog - empty backlog; run() completes and returns non-empty string
3. test_run_with_graphify_error - empty StructuredCodebaseSummary; run() still calls route_request

All dependencies (get_codebase_summary, post_sprint_backlog, route_request) are mocked via unittest.mock.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# Set up test encryption key before any imports
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ.setdefault("JIRA_ACCOUNT_EMAIL", "test@example.com")


def _make_encrypted(value: str) -> str:
    """Encrypt a value using the test key."""
    from cryptography.fernet import Fernet as _Fernet
    return _Fernet(os.environ["ENCRYPTION_KEY"].encode()).encrypt(value.encode()).decode()


def _make_mock_project():
    """Return a mock Project with fields needed by describe_pipeline.run()."""
    project = MagicMock()
    project.id = 1
    project.name = "Test Project"
    project.project_key = "PROJ"
    project.jira_url = "https://proj.atlassian.net"
    project.github_url = "https://github.com/org/repo"
    project.jira_token = _make_encrypted("jira-secret-token")
    project.github_token = _make_encrypted("github-secret-token")
    return project


def _make_mock_event():
    """Return a mock JiraCommentEvent."""
    event = MagicMock()
    event.issue.key = "PROJ-42"
    event.issue.fields = {"summary": "Add JWT authentication"}
    event.comment.body = "@hermes describe Add JWT login with refresh tokens"
    return event


def _make_stub_summary():
    """Return a StructuredCodebaseSummary with minimal data."""
    from services.graphify_service import StructuredCodebaseSummary
    return StructuredCodebaseSummary(
        directory_tree="backend/main.py\nbackend/database.py",
        key_files=["backend/main.py", "backend/database.py"],
        module_docs={"backend/main.py": "Main FastAPI application module."},
    )


def _make_stub_llm_response(content: str = "Elaborated description content."):
    """Return a mock LLMResponse."""
    from services.llm_router import LLMResponse
    return LLMResponse(provider="freellmapi", content=content, model="llama3")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_run_returns_generated_description():
    """Mock all three dependencies; assert run() returns the LLM content string."""
    backlog = [{"key": "PROJ-2", "summary": "Add login", "issue_type": "Story"}]

    with (
        patch("services.describe_pipeline.get_codebase_summary", return_value=_make_stub_summary()),
        patch("services.describe_pipeline.post_sprint_backlog", new_callable=AsyncMock) as mock_backlog,
        patch("services.describe_pipeline.route_request", return_value=_make_stub_llm_response(
            "Elaborated: feature adds login capability with JWT tokens."
        )),
    ):
        mock_backlog.return_value = backlog

        import asyncio
        from services.describe_pipeline import run

        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))

    assert isinstance(result, str)
    assert result == "Elaborated: feature adds login capability with JWT tokens."


def test_run_with_no_sprint_backlog():
    """Empty sprint backlog; run() completes and returns a non-empty string."""
    with (
        patch("services.describe_pipeline.get_codebase_summary", return_value=_make_stub_summary()),
        patch("services.describe_pipeline.post_sprint_backlog", new_callable=AsyncMock) as mock_backlog,
        patch("services.describe_pipeline.route_request", return_value=_make_stub_llm_response(
            "Feature description without sprint context."
        )),
    ):
        mock_backlog.return_value = []  # Empty backlog

        import asyncio
        from services.describe_pipeline import run

        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))

    assert isinstance(result, str)
    assert len(result) > 0


def test_run_with_graphify_error():
    """Empty StructuredCodebaseSummary from graphify; run() still calls route_request."""
    from services.graphify_service import StructuredCodebaseSummary

    empty_summary = StructuredCodebaseSummary()  # All empty fields

    with (
        patch("services.describe_pipeline.get_codebase_summary", return_value=empty_summary),
        patch("services.describe_pipeline.post_sprint_backlog", new_callable=AsyncMock) as mock_backlog,
        patch("services.describe_pipeline.route_request", return_value=_make_stub_llm_response(
            "Description even without codebase context."
        )) as mock_route,
    ):
        mock_backlog.return_value = [
            {"key": "PROJ-1", "summary": "Background task", "issue_type": "Task"}
        ]

        import asyncio
        from services.describe_pipeline import run

        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))

    # route_request must have been called even with empty codebase context
    mock_route.assert_called_once()
    assert isinstance(result, str)
    assert len(result) > 0
