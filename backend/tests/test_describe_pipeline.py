"""TDD tests for describe_pipeline.run().

Tests (5 total):
1. test_run_returns_generated_description — mocked dependencies; run() returns LLM content string
2. test_run_with_no_sprint_backlog — empty backlog; run() completes returns non-empty string
3. test_run_with_no_codebase_snapshot — get_codebase_snapshot returns None; run() still calls route_request
4. test_run_includes_snapshot_content_in_prompt — snapshot content (file paths) appears in LLM prompt (DESCCTX-02)
5. test_run_with_decrypt_failure — decrypt_credential raises; run() degrades gracefully, route_request still called

Dependencies (get_codebase_snapshot, post_sprint_backlog, route_request) mocked via unittest.mock.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from services.describe_pipeline import run

# Set up test encryption key before any module-level imports that read env vars
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ.setdefault("JIRA_ACCOUNT_EMAIL", "test@example.com")


def _make_encrypted(value: str) -> str:
    """Encrypt value using test key."""
    from cryptography.fernet import Fernet as _Fernet
    return _Fernet(os.environ["ENCRYPTION_KEY"].encode()).encrypt(value.encode()).decode()


def _make_mock_project():
    """Return mock Project fields needed by describe_pipeline.run()."""
    project = MagicMock()
    project.id = 1
    project.name = "Test Project"
    project.project_key = "PROJ"
    project.jira_url = "https://proj.atlassian.net"
    project.github_url = "https://github.com/org/repo"
    project.jira_token = _make_encrypted("jira-secret-token")
    project.github_token = _make_encrypted("github-secret-token")
    project.github_repo = _make_encrypted("org/repo")
    return project


def _make_mock_event():
    """Return mock JiraCommentEvent."""
    event = MagicMock()
    event.issue.key = "PROJ-42"
    event.issue.summary = "Add JWT authentication"
    event.comment.body = "@jarvis describe Add JWT login refresh tokens"
    return event


def _make_stub_snapshot() -> str:
    """Return a stub codebase snapshot string."""
    return (
        "# Codebase Snapshot\n"
        "## Services\n"
        "- backend/services/describe_pipeline.py\n"
        "- backend/services/hermes_client.py\n"
        "- backend/services/llm_router.py\n"
    )


def _make_stub_llm_response(content: str):
    """Return a stub LLM route_request response with .content attribute."""
    stub = MagicMock()
    stub.content = content
    return stub


def test_run_returns_generated_description():
    """Mocked dependencies; run() returns the LLM content string."""
    with (
        patch(
            "services.describe_pipeline.get_codebase_snapshot",
            new_callable=AsyncMock,
            return_value=_make_stub_snapshot(),
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
        ) as mock_backlog,
        patch(
            "services.describe_pipeline.route_request",
            return_value=_make_stub_llm_response(
                "Elaborated: feature adds login capability with JWT tokens."
            ),
        ),
    ):
        mock_backlog.return_value = [
            {"key": "PROJ-1", "summary": "Setup repo", "issue_type": "Task"},
        ]


        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))

        assert isinstance(result, str)
        assert result == "Elaborated: feature adds login capability with JWT tokens."


def test_run_with_no_sprint_backlog():
    """Empty sprint backlog; run() completes and returns non-empty string."""
    with (
        patch(
            "services.describe_pipeline.get_codebase_snapshot",
            new_callable=AsyncMock,
            return_value=_make_stub_snapshot(),
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
        ) as mock_backlog,
        patch(
            "services.describe_pipeline.route_request",
            return_value=_make_stub_llm_response(
                "Feature description without sprint context."
            ),
        ),
    ):
        mock_backlog.return_value = []  # Empty backlog


        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))

        assert isinstance(result, str)
        assert len(result) > 0


def test_run_with_no_codebase_snapshot():
    """get_codebase_snapshot returns None; run() still calls route_request (graceful degradation)."""
    with (
        patch(
            "services.describe_pipeline.get_codebase_snapshot",
            new_callable=AsyncMock,
            return_value=None,  # Snapshot unavailable
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
        ) as mock_backlog,
        patch(
            "services.describe_pipeline.route_request",
            return_value=_make_stub_llm_response(
                "Description even without codebase context."
            ),
        ) as mock_route,
    ):
        mock_backlog.return_value = [
            {"key": "PROJ-1", "summary": "Background task", "issue_type": "Task"},
        ]


        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))

        # route_request must be called even with no codebase snapshot
        mock_route.assert_called_once()
        assert isinstance(result, str)
        assert len(result) > 0


def test_run_includes_snapshot_content_in_prompt():
    """Snapshot content (real file paths) appears in the LLM prompt (DESCCTX-02)."""
    snapshot_text = (
        "## Services\n"
        "- backend/services/describe_pipeline.py\n"
        "- backend/services/hermes_client.py\n"
    )

    with (
        patch(
            "services.describe_pipeline.get_codebase_snapshot",
            new_callable=AsyncMock,
            return_value=snapshot_text,
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
        ) as mock_backlog,
        patch(
            "services.describe_pipeline.route_request",
            return_value=_make_stub_llm_response("Feature elaboration with codebase context."),
        ) as mock_route,
    ):
        mock_backlog.return_value = []


        asyncio.run(run(_make_mock_event(), _make_mock_project()))

        # Verify snapshot content appears in the prompt passed to route_request
        assert mock_route.called, "route_request should have been called"
        call_args = mock_route.call_args
        prompt_arg = call_args[0][1]  # Second positional arg is the prompt string

        assert "backend/services/describe_pipeline.py" in prompt_arg, (
            "Snapshot content (file path) must appear in LLM prompt for DESCCTX-02"
        )

def test_run_with_decrypt_failure():
    """decrypt_credential raises; run() still completes gracefully (CR-01)."""
    from cryptography.fernet import InvalidToken

    with (
        patch(
            "services.describe_pipeline.decrypt_credential",
            side_effect=InvalidToken,
        ),
        patch(
            "services.describe_pipeline.get_codebase_snapshot",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "services.describe_pipeline.route_request",
            return_value=_make_stub_llm_response("ok after decrypt failure"),
        ) as mock_route,
    ):
        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))
        mock_route.assert_called_once()
        assert isinstance(result, str)
