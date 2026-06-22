"""TDD tests for merge_pipeline.run() — PRMERGE-01, PRMERGE-02.

Tests (9 total):
1. test_run_no_pr_found — find_and_merge_pr returns None → informative comment posted,
   update_status NOT called, PipelineState.status ends as "complete" (not "failed").
2. test_run_success — find_and_merge_pr returns MergeResult(merged=True, sha="abc123", …)
   → update_status called with "Done", Jira comment contains "abc123" and PR URL,
   PipelineState.status="complete", draft_content is plain string.
3. test_run_status_update_fails_gracefully — update_status returns False → comment with
   SHA still posted, PipelineState.status="complete" (graceful degradation, not failure).
4. test_run_exception_sets_failed_status — find_and_merge_pr raises RuntimeError →
   PipelineState.status="failed", failure-notification Jira comment posted via
   hermes_post_comment containing "failed" and "PROJ-1".
5. test_run_reuses_existing_pipeline_state_row — PipelineState(stage="merge_pr",
   status="running") pre-created by the webhook before scheduling the task → run() must
   reuse that exact row (row count == 1 after run).
6. test_run_tokens_never_in_comment — github_token and jira_token literal fixture values
   must never appear in the text posted to Jira (T-17-05 token isolation).
7. test_run_triggers_codebase_rescan_on_success — successful merge triggers codebase
   re-scan; state_row.status still "complete" and SHA confirmation comment still posted.
8. test_run_rescan_failure_does_not_fail_merge — re-scan raises RuntimeError → merge
   outcome unaffected (state_row.status="complete", SHA comment posted unchanged).
9. test_run_no_pr_found_skips_rescan — find_and_merge_pr returns None → codebase_scan
   is NOT called since nothing was merged.

Uses StaticPool in-memory DB; unittest.mock.patch for all external dependencies.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

from database import Base  # noqa: E402
import models.project  # noqa: E402
import models.ticket_status  # noqa: E402
import models.pipeline_state  # noqa: E402
from models.pipeline_state import PipelineState  # noqa: E402
from models.project import Project  # noqa: E402
from services.crypto import encrypt_credential  # noqa: E402
from services.pr_creator import MergeResult  # noqa: E402

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PLAINTEXT_GITHUB_TOKEN = "ghp_SUPER_SECRET_TOKEN"
PLAINTEXT_JIRA_TOKEN = "jira_api_VERY_SECRET_KEY"


@pytest.fixture(autouse=True)
def reset_tables():
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)


def _make_mock_project():
    p = MagicMock()
    p.id = 1
    p.project_key = "PROJ"
    p.jira_url = "https://jira.example.com"
    p.jira_email = "bot@example.com"
    p.jira_token = encrypt_credential(PLAINTEXT_JIRA_TOKEN)
    p.github_token = encrypt_credential(PLAINTEXT_GITHUB_TOKEN)
    p.github_repo = encrypt_credential("owner/repo")
    return p


def _make_merge_result(sha: str = "abc123", pr_number: int = 42) -> MergeResult:
    return MergeResult(
        merged=True,
        sha=sha,
        pr_number=pr_number,
        pr_url="https://github.com/owner/repo/pull/42",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_no_pr_found():
    """find_and_merge_pr returns None → informative comment posted; update_status NOT called; status=complete."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=None),
        patch(
            "services.merge_pipeline.update_status", new_callable=AsyncMock
        ) as mock_update_status,
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ) as mock_post,
    ):
        from services.merge_pipeline import run

        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    mock_update_status.assert_not_called()
    mock_post.assert_called_once()
    posted_body = mock_post.call_args[0][4]
    assert "PROJ-1" in posted_body
    assert "jarvis/issue-PROJ-1" in posted_body

    db.refresh(state_row)
    assert state_row.status == "complete"
    assert isinstance(result, str)
    assert result  # non-empty informative message

    db.close()


@pytest.mark.asyncio
async def test_run_success():
    """find_and_merge_pr returns MergeResult → update_status("Done"), comment with SHA and PR URL, status=complete."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    merge_result = _make_merge_result(sha="abc123", pr_number=42)

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=merge_result),
        patch(
            "services.merge_pipeline.update_status", new_callable=AsyncMock, return_value=True
        ) as mock_update_status,
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ) as mock_post,
        patch(
            "services.merge_pipeline.codebase_scan_service.run", new_callable=AsyncMock
        ),
    ):
        from services.merge_pipeline import run

        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    # update_status called with "Done"
    mock_update_status.assert_called_once()
    call_args = mock_update_status.call_args[0]
    assert call_args[3] == "PROJ-1"
    assert call_args[4] == "Done"

    # comment posted with SHA and PR URL
    mock_post.assert_called_once()
    posted_body = mock_post.call_args[0][4]
    assert "abc123" in posted_body
    assert "https://github.com/owner/repo/pull/42" in posted_body

    db.refresh(state_row)
    assert state_row.status == "complete"
    assert "abc123" in (state_row.draft_content or "")

    assert "abc123" in result
    db.close()


@pytest.mark.asyncio
async def test_run_status_update_fails_gracefully():
    """update_status returns False → SHA comment still posted, status=complete (graceful degradation)."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    merge_result = _make_merge_result(sha="def456")

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=merge_result),
        patch(
            "services.merge_pipeline.update_status", new_callable=AsyncMock, return_value=False
        ),
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ) as mock_post,
        patch(
            "services.merge_pipeline.codebase_scan_service.run", new_callable=AsyncMock
        ),
    ):
        from services.merge_pipeline import run

        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    # SHA comment must still be posted despite status update failure
    mock_post.assert_called_once()
    posted_body = mock_post.call_args[0][4]
    assert "def456" in posted_body

    db.refresh(state_row)
    assert state_row.status == "complete"
    assert "def456" in result

    db.close()


@pytest.mark.asyncio
async def test_run_exception_sets_failed_status():
    """find_and_merge_pr raises RuntimeError → status=failed; failure notification posted."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    with (
        patch(
            "services.merge_pipeline.find_and_merge_pr",
            side_effect=RuntimeError("GitHub API 500"),
        ),
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ) as mock_post,
    ):
        from services.merge_pipeline import run

        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    # Failure notification must be posted
    mock_post.assert_called_once()
    posted_body = mock_post.call_args[0][4]
    assert "failed" in posted_body.lower()
    assert "PROJ-1" in posted_body

    db.refresh(state_row)
    assert state_row.status == "failed"
    db.close()


@pytest.mark.asyncio
async def test_run_reuses_existing_pipeline_state_row():
    """Webhook pre-creates PipelineState(merge_pr, running) → run() reuses it; row count stays 1."""
    project = _make_mock_project()
    db = TestingSession()

    # Pre-create the row as the webhook idempotency guard does
    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    merge_result = _make_merge_result()

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=merge_result),
        patch("services.merge_pipeline.update_status", new_callable=AsyncMock, return_value=True),
        patch("services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch(
            "services.merge_pipeline.codebase_scan_service.run", new_callable=AsyncMock
        ),
    ):
        from services.merge_pipeline import run

        await run(project, "PROJ-1", "Feature X", "Some description", db)

    # Only one row should exist (reused, not duplicated)
    row_count = (
        db.query(PipelineState)
        .filter(
            PipelineState.ticket_key == "PROJ-1",
            PipelineState.stage == "merge_pr",
        )
        .count()
    )
    assert row_count == 1

    db.close()


@pytest.mark.asyncio
async def test_run_tokens_never_in_comment():
    """T-17-05: github_token and jira_token must never appear in the comment text posted to Jira."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    merge_result = _make_merge_result(sha="sha9999")

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=merge_result),
        patch("services.merge_pipeline.update_status", new_callable=AsyncMock, return_value=True),
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ) as mock_post,
        patch(
            "services.merge_pipeline.codebase_scan_service.run", new_callable=AsyncMock
        ),
    ):
        from services.merge_pipeline import run

        await run(project, "PROJ-1", "Feature X", "Some description", db)

    mock_post.assert_called_once()
    posted_body = mock_post.call_args[0][4]

    # Token literals must never appear in Jira comment body
    assert PLAINTEXT_GITHUB_TOKEN not in posted_body, (
        f"github_token literal leaked into Jira comment: {posted_body!r}"
    )
    assert PLAINTEXT_JIRA_TOKEN not in posted_body, (
        f"jira_token literal leaked into Jira comment: {posted_body!r}"
    )

    db.close()


# ---------------------------------------------------------------------------
# New tests: post-merge codebase re-scan hook (SNAPSHOT-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_triggers_codebase_rescan_on_success():
    """SNAPSHOT-01: successful merge triggers codebase re-scan with correct args;
    state_row.status stays "complete" and SHA confirmation comment still posted."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    merge_result = _make_merge_result(sha="abc123", pr_number=42)

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=merge_result),
        patch(
            "services.merge_pipeline.update_status", new_callable=AsyncMock, return_value=True
        ),
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ) as mock_post,
        patch(
            "services.merge_pipeline.codebase_scan_service.run", new_callable=AsyncMock
        ) as mock_rescan,
    ):
        from services.merge_pipeline import run

        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    # re-scan must be called exactly once with the decrypted args
    mock_rescan.assert_awaited_once_with(
        "owner/repo",
        PLAINTEXT_GITHUB_TOKEN,
        project.id,
        db,
    )

    # SHA confirmation comment still posted
    mock_post.assert_called_once()
    posted_body = mock_post.call_args[0][4]
    assert "abc123" in posted_body

    db.refresh(state_row)
    assert state_row.status == "complete"

    db.close()


@pytest.mark.asyncio
async def test_run_rescan_failure_does_not_fail_merge():
    """SNAPSHOT-01 isolation: re-scan raises RuntimeError → merge outcome unaffected.
    state_row.status="complete", SHA comment posted, exception not leaked to Jira."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    merge_result = _make_merge_result(sha="abc123", pr_number=42)

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=merge_result),
        patch(
            "services.merge_pipeline.update_status", new_callable=AsyncMock, return_value=True
        ),
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ) as mock_post,
        patch(
            "services.merge_pipeline.codebase_scan_service.run",
            new_callable=AsyncMock,
            side_effect=RuntimeError("scan boom"),
        ),
    ):
        from services.merge_pipeline import run

        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    # merge state must still be complete despite scan failure
    db.refresh(state_row)
    assert state_row.status == "complete", (
        f"Expected 'complete' but got '{state_row.status}' — scan failure leaked into merge state"
    )

    # SHA comment must still be posted once (no scan-failure text in it)
    mock_post.assert_called_once()
    posted_body = mock_post.call_args[0][4]
    assert "abc123" in posted_body
    assert "scan boom" not in posted_body

    # return value must be the normal confirmation text
    assert "abc123" in result

    db.close()


@pytest.mark.asyncio
async def test_run_no_pr_found_skips_rescan():
    """No-PR branch: find_and_merge_pr returns None → codebase_scan NOT called."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="merge_pr", status="running"
    )
    db.add(state_row)
    db.commit()

    with (
        patch("services.merge_pipeline.find_and_merge_pr", return_value=None),
        patch(
            "services.merge_pipeline.update_status", new_callable=AsyncMock
        ),
        patch(
            "services.merge_pipeline.hermes_post_comment", new_callable=AsyncMock
        ),
        patch(
            "services.merge_pipeline.codebase_scan_service.run", new_callable=AsyncMock
        ) as mock_rescan,
    ):
        from services.merge_pipeline import run

        await run(project, "PROJ-1", "Feature X", "Some description", db)

    # nothing was merged — re-scan must NOT be triggered
    mock_rescan.assert_not_called()

    db.close()
