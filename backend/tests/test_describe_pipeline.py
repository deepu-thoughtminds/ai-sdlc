"""TDD tests for describe_pipeline.run() — Phase 33 revision.

Tests (5 total):
1. test_run_returns_generated_description — mocked deps; run() returns opencode content
2. test_run_with_no_sprint_backlog — empty backlog; run() completes returns non-empty string
3. test_run_cbm_unavailable — cbm_call raises; run() still calls _run_opencode_describe
4. test_run_graph_context_in_prompt — graph node names appear in prompt passed to opencode
5. test_run_with_decrypt_failure — decrypt raises; run() degrades gracefully
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from database import get_database
from services.describe_pipeline import run

_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ.setdefault("JIRA_ACCOUNT_EMAIL", "test@example.com")


def _make_encrypted(value: str) -> str:
    from cryptography.fernet import Fernet as _Fernet
    return _Fernet(os.environ["ENCRYPTION_KEY"].encode()).encrypt(value.encode()).decode()


def _make_mock_project():
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
    event = MagicMock()
    event.issue.key = "PROJ-42"
    event.issue.summary = "Add JWT authentication"
    event.comment.body = "@jarvis describe Add JWT login refresh tokens"
    return event


def _graph_nodes():
    return {
        "nodes": [
            {"name": "auth_service", "file": "backend/services/auth.py"},
            {"name": "JwtPayload", "file": "backend/models/jwt.py"},
        ]
    }


def test_run_returns_generated_description():
    """Mocked deps; run() returns the opencode-generated content string."""
    with (
        patch(
            "services.describe_pipeline.cbm_call",
            return_value=_graph_nodes(),
        ),
        patch(
            "services.describe_pipeline.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=_graph_nodes(),
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
            return_value=[{"key": "PROJ-1", "summary": "Setup repo", "issue_type": "Task"}],
        ),
        patch(
            "services.describe_pipeline._run_opencode_describe",
            new_callable=AsyncMock,
            return_value=("Elaborated: feature adds login capability with JWT tokens.", ""),
        ),
    ):
        result = asyncio.run(run(_make_mock_event(), _make_mock_project(), get_database()))
        assert isinstance(result, str)
        assert "JWT" in result


def test_run_with_no_sprint_backlog():
    """Empty sprint backlog; run() completes and returns non-empty string."""
    with (
        patch(
            "services.describe_pipeline.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=_graph_nodes(),
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "services.describe_pipeline._run_opencode_describe",
            new_callable=AsyncMock,
            return_value=("Feature description without sprint context.", ""),
        ),
    ):
        result = asyncio.run(run(_make_mock_event(), _make_mock_project(), get_database()))
        assert isinstance(result, str)
        assert len(result) > 0


def test_run_cbm_unavailable():
    """cbm search_graph raises; run() still calls _run_opencode_describe (CTX-02 graceful)."""
    with (
        patch(
            "services.describe_pipeline.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=RuntimeError("cbm binary not found"),
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "services.describe_pipeline._run_opencode_describe",
            new_callable=AsyncMock,
            return_value=("Description even without graph context.", ""),
        ) as mock_opencode,
    ):
        result = asyncio.run(run(_make_mock_event(), _make_mock_project(), get_database()))
        mock_opencode.assert_called_once()
        assert isinstance(result, str)


def test_run_graph_context_in_prompt():
    """Graph node names from cbm appear in the prompt passed to opencode (CTX-02)."""
    captured_prompt: list[str] = []

    async def _capture(prompt: str) -> tuple[str, str]:
        captured_prompt.append(prompt)
        return ("Feature elaboration with graph context.", "")

    with (
        patch(
            "services.describe_pipeline.asyncio.to_thread",
            new_callable=AsyncMock,
            return_value=_graph_nodes(),
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "services.describe_pipeline._run_opencode_describe",
            side_effect=_capture,
        ),
    ):
        asyncio.run(run(_make_mock_event(), _make_mock_project(), get_database()))

    assert captured_prompt, "_run_opencode_describe was not called"
    prompt = captured_prompt[0]
    assert "auth_service" in prompt, "Graph node name must appear in prompt (CTX-02)"
    assert "backend/services/auth.py" in prompt, "Graph file path must appear in prompt"


def test_run_with_decrypt_failure():
    """decrypt_credential raises; run() degrades gracefully."""
    from cryptography.fernet import InvalidToken

    with (
        patch(
            "services.describe_pipeline.decrypt_credential",
            side_effect=InvalidToken,
        ),
        patch(
            "services.describe_pipeline.asyncio.to_thread",
            new_callable=AsyncMock,
            side_effect=RuntimeError("cbm unavailable"),
        ),
        patch(
            "services.describe_pipeline.post_sprint_backlog",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch(
            "services.describe_pipeline._run_opencode_describe",
            new_callable=AsyncMock,
            return_value=("ok after decrypt failure", ""),
        ) as mock_opencode,
    ):
        result = asyncio.run(run(_make_mock_event(), _make_mock_project(), get_database()))
        mock_opencode.assert_called_once()
        assert isinstance(result, str)
