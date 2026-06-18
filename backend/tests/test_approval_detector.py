"""TDD tests for approval_detector service.

Tests (12 total):
1. test_is_approval_returns_true_for_approved
2. test_is_approval_returns_true_for_lgtm
3. test_is_approval_returns_true_for_plus_one
4. test_is_approval_returns_false_for_random
5. test_detect_and_apply_approval_updates_jira
6. test_detect_and_apply_approval_noop_when_no_pending
7. test_detect_and_apply_approval_noop_when_not_approval_text
8. test_detect_and_apply_approval_architecture_stage_posts_comment (NEW)
9. test_detect_and_apply_approval_architecture_with_developer_calls_assign (NEW)
10. test_parse_developer_from_approval_returns_name (NEW)
11. test_parse_developer_from_approval_returns_none_when_no_mention (NEW)
12. test_architecture_approval_priority_over_describe (NEW)

Uses StaticPool + DB session + mocked JiraClient pattern.
T-03-10: Token-based matching prevents substring false-positives (unapproved ≠ approved).
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE importing any app modules.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# Set up a shared in-memory SQLite engine using StaticPool so all connections
# see the same database.
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Import app modules after setting env vars.
from database import Base  # noqa: E402
import models.project  # noqa: E402
import models.ticket_status  # noqa: E402
import models.pipeline_state  # noqa: E402
from models.project import Project  # noqa: E402
from models.pipeline_state import PipelineState  # noqa: E402
from models.webhook import JiraCommentEvent, JiraIssue, JiraComment  # noqa: E402

# Create tables on our StaticPool-backed engine.
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


def _make_project(db) -> Project:
    """Insert a Project row and return the ORM object."""
    from services.crypto import encrypt_credential
    project = Project(
        name="Test Project",
        project_key="PROJ",
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


def _make_event(issue_key: str = "PROJ-1", body: str = "LGTM") -> JiraCommentEvent:
    """Build a minimal JiraCommentEvent for tests."""
    return JiraCommentEvent(
        webhook_event="comment_created",
        issue=JiraIssue(id="1", key=issue_key),
        comment=JiraComment(id="c1", body=body),
    )


# ---------------------------------------------------------------------------
# is_approval tests
# ---------------------------------------------------------------------------


def test_is_approval_returns_true_for_approved():
    """is_approval('Approved!') returns True (case-insensitive token match)."""
    from services.approval_detector import is_approval
    assert is_approval("Approved!") is True


def test_is_approval_returns_true_for_lgtm():
    """is_approval('LGTM') returns True."""
    from services.approval_detector import is_approval
    assert is_approval("LGTM") is True


def test_is_approval_returns_true_for_plus_one():
    """is_approval('+1 looks good') returns True."""
    from services.approval_detector import is_approval
    assert is_approval("+1 looks good") is True


def test_is_approval_returns_false_for_random():
    """is_approval('What about the edge case?') returns False."""
    from services.approval_detector import is_approval
    assert is_approval("What about the edge case?") is False


def test_is_approval_returns_false_for_unapproved():
    """is_approval('unapproved') returns False — T-03-10: no substring match."""
    from services.approval_detector import is_approval
    assert is_approval("unapproved") is False


def test_is_approval_returns_false_for_disapprove():
    """is_approval('I disapprove of this') returns False — T-03-10: no substring match."""
    from services.approval_detector import is_approval
    assert is_approval("I disapprove of this") is False


# ---------------------------------------------------------------------------
# detect_and_apply_approval tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_and_apply_approval_updates_jira():
    """When a PipelineState row with status='awaiting_approval' exists and comment is 'LGTM',
    detect_and_apply_approval calls JiraClient.update_description with draft_content and
    sets status='approved'.
    """
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db)

        # Insert awaiting_approval pipeline state row
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

        event = _make_event(issue_key="PROJ-1", body="LGTM")

        with patch("services.approval_detector.JiraClient") as MockJiraClient, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
            mock_instance = MagicMock()
            mock_instance.update_description.return_value = {}
            MockJiraClient.return_value = mock_instance

            result = await detect_and_apply_approval(event, db, project)

        assert result is True
        mock_instance.update_description.assert_called_once_with("PROJ-1", "Elaborated description.")

        # Verify status was updated
        db.refresh(ps)
        assert ps.status == "approved"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_noop_when_no_pending():
    """When no PipelineState row with status='awaiting_approval' exists, returns False
    and JiraClient.update_description is NOT called.
    """
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db)
        # No PipelineState rows inserted

        event = _make_event(issue_key="PROJ-1", body="LGTM")

        with patch("services.approval_detector.JiraClient") as MockJiraClient, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
            mock_instance = MagicMock()
            MockJiraClient.return_value = mock_instance

            result = await detect_and_apply_approval(event, db, project)

        assert result is False
        mock_instance.update_description.assert_not_called()
    finally:
        db.close()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_noop_when_not_approval_text():
    """When a PipelineState row exists but comment text is not an approval keyword,
    returns False and the row status remains unchanged.
    """
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db)

        # Insert awaiting_approval row
        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="describe",
            status="awaiting_approval",
            draft_content="Some draft.",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

        event = _make_event(issue_key="PROJ-1", body="Can you change the wording?")

        with patch("services.approval_detector.JiraClient") as MockJiraClient, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
            mock_instance = MagicMock()
            MockJiraClient.return_value = mock_instance

            result = await detect_and_apply_approval(event, db, project)

        assert result is False
        mock_instance.update_description.assert_not_called()

        # Row status unchanged
        db.refresh(ps)
        assert ps.status == "awaiting_approval"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# New tests: architecture stage approval (Tests 8-12)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_and_apply_approval_architecture_stage_posts_comment():
    """Test 8: When a PipelineState row with stage='architecture' and
    status='awaiting_approval' exists and comment is 'LGTM', detect_and_apply_approval
    calls JiraClient.add_comment with draft_content and sets status='approved'.
    """
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db)

        # Insert awaiting_approval architecture pipeline state row
        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="architecture",
            status="awaiting_approval",
            draft_content="Architecture options draft.",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

        event = _make_event(issue_key="PROJ-1", body="LGTM")

        with patch("services.approval_detector.JiraClient") as MockJiraClient, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
            mock_instance = MagicMock()
            mock_instance.add_comment = AsyncMock(return_value={})
            MockJiraClient.return_value = mock_instance

            result = await detect_and_apply_approval(event, db, project)

        assert result is True
        mock_instance.add_comment.assert_called_once_with("PROJ-1", "Architecture options draft.")

        # Verify status was updated to approved
        db.refresh(ps)
        assert ps.status == "approved"
    finally:
        db.close()


@pytest.mark.asyncio
async def test_detect_and_apply_approval_architecture_with_developer_calls_assign():
    """Test 9: When architecture approval comment includes @developer name,
    detect_and_apply_approval calls assign_pipeline.run after posting the comment.
    """
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db)

        ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="architecture",
            status="awaiting_approval",
            draft_content="Architecture options.",
        )
        db.add(ps)
        db.commit()
        db.refresh(ps)

        event = _make_event(issue_key="PROJ-1", body="approved @john.doe")

        with patch("services.approval_detector.JiraClient") as MockJiraClient, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"), \
             patch("services.approval_detector.assign_pipeline") as mock_assign_pipeline:
            mock_instance = MagicMock()
            mock_instance.add_comment = AsyncMock(return_value={})
            MockJiraClient.return_value = mock_instance
            mock_assign_pipeline.run = AsyncMock(return_value=None)

            result = await detect_and_apply_approval(event, db, project)

        assert result is True
        mock_assign_pipeline.run.assert_called_once()
        call_args = mock_assign_pipeline.run.call_args
        # Verify @john.doe is in the call args
        assert "@john.doe" in str(call_args)
    finally:
        db.close()


def test_parse_developer_from_approval_returns_name():
    """Test 10: _parse_developer_from_approval('lgtm @john.doe') returns 'john.doe'."""
    from services.approval_detector import _parse_developer_from_approval
    result = _parse_developer_from_approval("lgtm @john.doe")
    assert result == "john.doe"


def test_parse_developer_from_approval_returns_none_when_no_mention():
    """Test 11: _parse_developer_from_approval('approved') returns None."""
    from services.approval_detector import _parse_developer_from_approval
    result = _parse_developer_from_approval("approved")
    assert result is None


@pytest.mark.asyncio
async def test_architecture_approval_priority_over_describe():
    """Test 12: When both architecture and describe rows are awaiting_approval,
    architecture is handled first (priority rule).
    """
    from services.approval_detector import detect_and_apply_approval

    db = TestingSession()
    try:
        project = _make_project(db)

        # Insert BOTH architecture and describe awaiting_approval rows
        arch_ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="architecture",
            status="awaiting_approval",
            draft_content="Arch draft.",
        )
        desc_ps = PipelineState(
            project_id=project.id,
            ticket_key="PROJ-1",
            stage="describe",
            status="awaiting_approval",
            draft_content="Desc draft.",
        )
        db.add(arch_ps)
        db.add(desc_ps)
        db.commit()
        db.refresh(arch_ps)
        db.refresh(desc_ps)

        event = _make_event(issue_key="PROJ-1", body="LGTM")

        with patch("services.approval_detector.JiraClient") as MockJiraClient, \
             patch("services.approval_detector.decrypt_credential", return_value="plaintext-token"):
            mock_instance = MagicMock()
            mock_instance.add_comment = AsyncMock(return_value={})
            mock_instance.update_description = MagicMock(return_value={})
            MockJiraClient.return_value = mock_instance

            result = await detect_and_apply_approval(event, db, project)

        assert result is True
        # Architecture approval uses add_comment, not update_description
        mock_instance.add_comment.assert_called_once_with("PROJ-1", "Arch draft.")
        mock_instance.update_description.assert_not_called()

        # Architecture row is approved; describe row is unchanged
        db.refresh(arch_ps)
        db.refresh(desc_ps)
        assert arch_ps.status == "approved"
        assert desc_ps.status == "awaiting_approval"
    finally:
        db.close()
