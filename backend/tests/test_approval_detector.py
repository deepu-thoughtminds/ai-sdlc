"""Tests for approval_detector.detect_and_apply_approval().

Uses the shared mongomock fixtures in conftest.py.
"""

from unittest.mock import AsyncMock, patch

import pytest

from database import get_database
from models.webhook import JiraComment, JiraCommentEvent, JiraIssue
from repositories import pipeline_state_repo
from services.crypto import encrypt_credential
from tests.support import make_project


def _make_project(db, project_key="PROJ"):
    return make_project(
        db,
        name="Test Project",
        project_key=project_key,
        jira_url="https://test.atlassian.net",
        confluence_url="https://test.atlassian.net/wiki",
        jira_token=encrypt_credential("fake-jira-token"),
        github_token=encrypt_credential("fake-github-token"),
        confluence_token=encrypt_credential("fake-confluence-token"),
        github_repo=encrypt_credential("acme/my-app"),
    )


def _make_event(issue_key: str = "PROJ-1", body: str = "@jarvis approve story description") -> JiraCommentEvent:
    return JiraCommentEvent(
        webhook_event="comment_created",
        issue=JiraIssue(id="1", key=issue_key),
        comment=JiraComment(id="c1", body=body),
    )


@pytest.mark.asyncio
async def test_detect_and_apply_approval_story_description_updates_jira():
    """approve_subcmd='story description' + awaiting_approval row -> put_description called, status='approved'."""
    from services.approval_detector import detect_and_apply_approval

    db = get_database()
    project = _make_project(db)
    ps = pipeline_state_repo.create(
        db, project.id, "PROJ-1", "describe",
        status="awaiting_approval", draft_content="Elaborated description.",
    )

    event = _make_event(issue_key="PROJ-1")

    with patch("services.approval_detector.hermes_put_description", new_callable=AsyncMock) as mock_put, \
         patch("services.approval_detector.hermes_post_comment", new_callable=AsyncMock), \
         patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
        mock_put.return_value = {}
        result = await detect_and_apply_approval(event, db, project, "story description")

    assert result is True
    mock_put.assert_called_once()
    put_args = mock_put.call_args[0]
    assert "Elaborated description." in put_args
    assert pipeline_state_repo.get(db, ps.id).status == "approved"


@pytest.mark.asyncio
async def test_detect_and_apply_approval_noop_when_no_pending():
    """No awaiting_approval row -> returns False, hermes_put_description not called."""
    from services.approval_detector import detect_and_apply_approval

    db = get_database()
    project = _make_project(db, project_key="PROJ99")
    event = _make_event(issue_key="PROJ-99")

    with patch("services.approval_detector.hermes_put_description", new_callable=AsyncMock) as mock_put, \
         patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
        result = await detect_and_apply_approval(event, db, project, "story description")

    assert result is False
    mock_put.assert_not_called()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_noop_for_wrong_stage():
    """approve_subcmd='architecture' with awaiting_approval describe row -> returns False (stage mismatch)."""
    from services.approval_detector import detect_and_apply_approval

    db = get_database()
    project = _make_project(db, project_key="PROJ2")
    pipeline_state_repo.create(
        db, project.id, "PROJ-2", "describe",
        status="awaiting_approval", draft_content="Some description.",
    )

    event = _make_event(issue_key="PROJ-2")

    with patch("services.approval_detector.hermes_put_description", new_callable=AsyncMock) as mock_put, \
         patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
        result = await detect_and_apply_approval(event, db, project, "architecture")

    assert result is False
    mock_put.assert_not_called()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_skips_agent_comment():
    """Comment body containing [jarvis-bot] marker -> returns False (no self-trigger)."""
    from services.approval_detector import detect_and_apply_approval

    db = get_database()
    project = _make_project(db, project_key="PROJSKIP")
    event = _make_event(issue_key="PROJ-1", body="[jarvis-bot] @jarvis approve story description")

    with patch("services.approval_detector.hermes_put_description", new_callable=AsyncMock) as mock_put:
        result = await detect_and_apply_approval(event, db, project, "story description")

    assert result is False
    mock_put.assert_not_called()
