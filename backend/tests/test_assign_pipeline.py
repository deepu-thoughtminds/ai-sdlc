"""TDD tests for assign_pipeline service.

Tests (4 total):
1. test_assign_pipeline_calls_lookup_user
2. test_assign_pipeline_calls_assign_issue
3. test_assign_pipeline_posts_confirmation_comment
4. test_assign_pipeline_user_not_found

All JiraClient calls are mocked; no real DB required (project is a mock object).
T-03-11: raw_assignee is passed to Jira /user/search as a query param, not interpolated.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

# Set env vars BEFORE importing any app modules.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# Import app modules after setting env vars.
from models.webhook import JiraCommentEvent, JiraIssue, JiraComment  # noqa: E402
from services.mention_parser import MentionResult  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project() -> MagicMock:
    """Return a mock Project with the fields assign_pipeline needs."""
    project = MagicMock()
    project.jira_url = "https://test.atlassian.net"
    project.jira_token = "encrypted-token"
    return project


def _make_event(issue_key: str = "PROJ-1", body: str = "@hermes assign @john.doe") -> JiraCommentEvent:
    """Build a minimal JiraCommentEvent for tests."""
    return JiraCommentEvent(
        webhook_event="comment_created",
        issue=JiraIssue(id="1", key=issue_key),
        comment=JiraComment(id="c1", body=body),
    )


def _make_mention(extra: str = "@john.doe") -> MentionResult:
    """Build a MentionResult for the assign stage."""
    return MentionResult(mention_target="hermes", stage="assign", extra=extra)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assign_pipeline_calls_lookup_user():
    """run() with '@john.doe' in mention_result.extra calls lookup_user('john.doe')."""
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@john.doe")

    with patch("services.assign_pipeline.JiraClient") as MockJiraClient, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_instance = MagicMock()
        mock_instance.lookup_user.return_value = "ACCOUNT123"
        mock_instance.assign_issue.return_value = {}
        mock_instance.add_comment.return_value = {}
        MockJiraClient.return_value = mock_instance

        await run(event, project, mention_result)

    mock_instance.lookup_user.assert_called_once_with("john.doe")


@pytest.mark.asyncio
async def test_assign_pipeline_calls_assign_issue():
    """run() calls assign_issue(issue_key, account_id) after lookup_user."""
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@john.doe")

    with patch("services.assign_pipeline.JiraClient") as MockJiraClient, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_instance = MagicMock()
        mock_instance.lookup_user.return_value = "ACCOUNT123"
        mock_instance.assign_issue.return_value = {}
        mock_instance.add_comment.return_value = {}
        MockJiraClient.return_value = mock_instance

        await run(event, project, mention_result)

    mock_instance.assign_issue.assert_called_once_with("PROJ-1", "ACCOUNT123")


@pytest.mark.asyncio
async def test_assign_pipeline_posts_confirmation_comment():
    """run() calls add_comment after successful assign with body containing the assignee name."""
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@john.doe")

    with patch("services.assign_pipeline.JiraClient") as MockJiraClient, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_instance = MagicMock()
        mock_instance.lookup_user.return_value = "ACCOUNT123"
        mock_instance.assign_issue.return_value = {}
        mock_instance.add_comment.return_value = {}
        MockJiraClient.return_value = mock_instance

        await run(event, project, mention_result)

    assert mock_instance.add_comment.called
    call_args = mock_instance.add_comment.call_args
    # First positional arg should be the issue key
    assert call_args[0][0] == "PROJ-1"
    # Second positional arg (body) should mention the assignee name
    body = call_args[0][1]
    assert "john.doe" in body


@pytest.mark.asyncio
async def test_assign_pipeline_user_not_found():
    """When lookup_user returns None, add_comment is called with 'not found' message,
    and assign_issue is NOT called. No exception raised.
    """
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@ghost.user")

    with patch("services.assign_pipeline.JiraClient") as MockJiraClient, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_instance = MagicMock()
        mock_instance.lookup_user.return_value = None
        mock_instance.add_comment.return_value = {}
        MockJiraClient.return_value = mock_instance

        # Should not raise
        await run(event, project, mention_result)

    mock_instance.assign_issue.assert_not_called()
    assert mock_instance.add_comment.called
    call_args = mock_instance.add_comment.call_args
    body = call_args[0][1]
    assert "not found" in body.lower() or "ghost.user" in body
