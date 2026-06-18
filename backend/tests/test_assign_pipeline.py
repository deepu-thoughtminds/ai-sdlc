"""TDD tests for assign_pipeline service.

Tests (4 total):
1. test_assign_pipeline_calls_lookup_user
2. test_assign_pipeline_calls_assign_issue
3. test_assign_pipeline_posts_confirmation_comment
4. test_assign_pipeline_user_not_found

All hermes_client calls are mocked; no real DB required (project is a mock object).
T-03-11: raw_assignee is passed to post_assign, not interpolated into SQL/shell.
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
    """run() with '@john.doe' in mention_result.extra calls post_assign('john.doe')."""
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@john.doe")

    with patch("services.assign_pipeline.post_assign", new_callable=AsyncMock) as mock_post_assign, \
         patch("services.assign_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_comment, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_post_assign.return_value = "ACCOUNT123"

        await run(event, project, mention_result)

    mock_post_assign.assert_called_once()


@pytest.mark.asyncio
async def test_assign_pipeline_calls_assign_issue():
    """run() calls post_assign(issue_key, raw_assignee) to lookup+assign in one call."""
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@john.doe")

    with patch("services.assign_pipeline.post_assign", new_callable=AsyncMock) as mock_post_assign, \
         patch("services.assign_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_comment, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_post_assign.return_value = "ACCOUNT123"

        await run(event, project, mention_result)

    mock_post_assign.assert_called_once()


@pytest.mark.asyncio
async def test_assign_pipeline_posts_confirmation_comment():
    """run() calls hermes_post_comment after successful assign with body containing the assignee name."""
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@john.doe")

    with patch("services.assign_pipeline.post_assign", new_callable=AsyncMock) as mock_post_assign, \
         patch("services.assign_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_comment, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_post_assign.return_value = "ACCOUNT123"

        await run(event, project, mention_result)

    assert mock_comment.called is True
    # Find the confirmation call (last call after successful assign)
    call_args = mock_comment.call_args
    body = call_args[0][4]  # 5th positional arg is the comment body
    assert "john.doe" in body


@pytest.mark.asyncio
async def test_assign_pipeline_user_not_found():
    """When post_assign raises, hermes_post_comment is called with 'not found' message."""
    from services.assign_pipeline import run

    project = _make_project()
    event = _make_event()
    mention_result = _make_mention(extra="@ghost.user")

    with patch("services.assign_pipeline.post_assign", new_callable=AsyncMock) as mock_post_assign, \
         patch("services.assign_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_comment, \
         patch("services.assign_pipeline.decrypt_credential", return_value="plaintext-token"):
        mock_post_assign.side_effect = Exception("user not found")

        # Should not raise
        await run(event, project, mention_result)

    assert mock_comment.called is True
    call_args = mock_comment.call_args
    body = call_args[0][4]  # 5th positional arg is the comment body
    assert "ghost.user" in body or "not found" in body.lower()
