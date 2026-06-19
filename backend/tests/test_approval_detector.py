"""Tests for approval_detector.detect_and_apply_approval().

Approval is now entirely mention-based — is_approval() and APPROVAL_KEYWORDS
have been removed. detect_and_apply_approval receives the sub-command directly
from mention_parser via the webhook router.

Tests:
1. test_detect_and_apply_approval_story_description_updates_jira
2. test_detect_and_apply_approval_noop_when_no_pending
3. test_detect_and_apply_approval_noop_for_wrong_stage
4. test_detect_and_apply_approval_skips_agent_comment
"""

import os
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing app modules.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Import app modules after env vars are set.
from database import Base  # noqa: E402
import models.ticket_status  # noqa: E402,F401
from models.pipeline_state import PipelineState  # noqa: E402
from models.project import Project  # noqa: E402
from models.webhook import JiraComment, JiraCommentEvent, JiraIssue  # noqa: E402
from services.crypto import encrypt_credential  # noqa: E402

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


def _make_project(db, project_key="PROJ"):
    project = Project(
        name="Test Project",
        project_key=project_key,
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

    db = TestingSession()
    try:
        project = _make_project(db)
        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="describe",
            status="awaiting_approval",
            draft_content="Elaborated description.",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

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
        db.refresh(ps)
        assert ps.status == "approved"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_noop_when_no_pending():
    """No awaiting_approval row -> returns False, hermes_put_description not called."""
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db, project_key="PROJ99")
        event = _make_event(issue_key="PROJ-99")

        with patch("services.approval_detector.hermes_put_description", new_callable=AsyncMock) as mock_put, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
            result = await detect_and_apply_approval(event, db, project, "story description")

        assert result is False
        mock_put.assert_not_called()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_noop_for_wrong_stage():
    """approve_subcmd='architecture' with awaiting_approval describe row -> returns False (stage mismatch)."""
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db, project_key="PROJ2")
        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-2",
            stage="describe",
            status="awaiting_approval",
            draft_content="Some description.",
        )
        db.add(ps)
        db.commit()

        event = _make_event(issue_key="PROJ-2")

        with patch("services.approval_detector.hermes_put_description", new_callable=AsyncMock) as mock_put, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
            result = await detect_and_apply_approval(event, db, project, "architecture")

        assert result is False
        mock_put.assert_not_called()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_skips_agent_comment():
    """Comment body containing [jarvis-bot] marker -> returns False (no self-trigger)."""
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db, project_key="PROJSKIP")
        event = _make_event(issue_key="PROJ-1", body="[jarvis-bot] @jarvis approve story description")

        with patch("services.approval_detector.hermes_put_description", new_callable=AsyncMock) as mock_put:
            result = await detect_and_apply_approval(event, db, project, "story description")

        assert result is False
        mock_put.assert_not_called()
    finally:
        db.close()
