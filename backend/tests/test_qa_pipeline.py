"""Tests for services/qa_pipeline.py — TESTEXEC-01, TESTEXEC-02, AUTOFIX-04.

Follows the test_dev_pipeline.py pattern: StaticPool in-memory DB,
unittest.mock.patch for all external dependencies, asyncio.run() to drive
run() via pytest-asyncio.

Coverage:
  T-23-03: workspace cleanup always runs in finally block.
  T-23-04: qa_attempt is set to 0 and committed BEFORE any execution begins.
  Jira comment posting on both success and failure paths.
  PipelineState.status transitions (running -> complete / failed).
  Fresh clone (never reusing dev/merge pipeline workspace).
  Static T-23-01 gate: no shell=True anywhere in qa_pipeline.py source.
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
from services.crypto import encrypt_credential  # noqa: E402
from services.test_executor import TestResult  # noqa: E402

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


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
    p.jira_token = encrypt_credential("jira-secret")
    p.github_token = encrypt_credential("gh-secret")
    p.github_repo = encrypt_credential("owner/repo")
    return p


def _make_cloned_repo(path="/tmp/fake-qa-workspace"):
    from services.repo_clone import ClonedRepo
    return ClonedRepo(workspace_path=path, owner="owner", repo="repo")


def _make_state_row(db, project_id=1, status="running"):
    state_row = PipelineState(
        project_id=project_id, ticket_key="PROJ-1", stage="qa", status=status
    )
    db.add(state_row)
    db.commit()
    return state_row


@pytest.mark.asyncio
async def test_qa_attempt_set_to_zero_before_execution():
    """run_static_analysis raises immediately -> qa_attempt==0 persists in DB.

    T-23-04: the commit before execution must have persisted qa_attempt=0
    even though execution itself failed afterward.
    """
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    state_row = _make_state_row(db)

    with (
        patch("services.qa_pipeline.clone_repository", return_value=_make_cloned_repo()),
        patch("services.qa_pipeline.run_static_analysis", side_effect=RuntimeError("boom")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    db.refresh(state_row)
    assert state_row.qa_attempt == 0
    db.close()


@pytest.mark.asyncio
async def test_workspace_cleaned_up_on_success():
    """Successful static analysis run -> shutil.rmtree called with workspace path (T-23-03)."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    _make_state_row(db)

    cloned = _make_cloned_repo("/tmp/qa-success-workspace")
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree") as mock_rmtree,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/qa-success-workspace", ignore_errors=True)
    db.close()


@pytest.mark.asyncio
async def test_workspace_cleaned_up_on_failure():
    """clone succeeds, run_static_analysis raises -> shutil.rmtree still called (T-23-03)."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    _make_state_row(db)

    cloned = _make_cloned_repo("/tmp/qa-failure-workspace")

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", side_effect=RuntimeError("tool crashed")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree") as mock_rmtree,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/qa-failure-workspace", ignore_errors=True)
    db.close()


@pytest.mark.asyncio
async def test_workspace_cleaned_up_on_timeout():
    """run_static_analysis returns a timed_out result -> shutil.rmtree still called."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    _make_state_row(db)

    cloned = _make_cloned_repo("/tmp/qa-timeout-workspace")
    results = [
        TestResult(tool="bandit", returncode=-1, stdout="", stderr="Command timed out after 120s", timed_out=True)
    ]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree") as mock_rmtree,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/qa-timeout-workspace", ignore_errors=True)
    db.close()


@pytest.mark.asyncio
async def test_jira_comment_posted_on_success():
    """Successful run -> hermes_post_comment called once with PASSED/FAILED text."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    comment_body = mock_post.call_args[0][4]
    assert "PASSED" in comment_body or "FAILED" in comment_body
    db.close()


@pytest.mark.asyncio
async def test_jira_comment_posted_on_failure():
    """Even when pipeline raises, hermes_post_comment is called with a failure message.

    Also guards against the NameError regression: jira_token/jira_email must be
    bound before the try block so Step 6 can run after an exception.
    """
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    _make_state_row(db)

    with (
        patch("services.qa_pipeline.clone_repository", side_effect=RuntimeError("clone failed")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    comment_body = mock_post.call_args[0][4]
    assert "failed" in comment_body.lower()
    db.close()


@pytest.mark.asyncio
async def test_jira_comment_posted_on_failure_before_jira_token_assigned():
    """decrypt_credential raises BEFORE jira_token assignment -> no NameError; comment still posted."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    _make_state_row(db)

    with (
        patch("services.qa_pipeline.decrypt_credential", side_effect=RuntimeError("decrypt failed")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        # Must not raise NameError — failure path must complete cleanly.
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    db.close()


@pytest.mark.asyncio
async def test_pipeline_state_status_complete_on_success():
    """Successful run -> state_row.status == 'complete'."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    state_row = _make_state_row(db)

    cloned = _make_cloned_repo()
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    db.refresh(state_row)
    assert state_row.status == "complete"
    db.close()


@pytest.mark.asyncio
async def test_pipeline_state_status_failed_on_exception():
    """Exception during execution -> state_row.status == 'failed'."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    state_row = _make_state_row(db)

    with (
        patch("services.qa_pipeline.clone_repository", side_effect=RuntimeError("clone failed")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    db.refresh(state_row)
    assert state_row.status == "failed"
    db.close()


@pytest.mark.asyncio
async def test_fresh_clone_not_dev_workspace():
    """clone_repository called exactly once inside run() with decrypted github_repo."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = TestingSession()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned) as mock_clone,
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_clone.assert_called_once_with("owner/repo", "gh-secret")
    db.close()


def test_no_shell_true_in_qa_pipeline():
    """Static assertion: shell=True is never used as actual code in qa_pipeline.py (T-23-01).

    Mirrors the plan's verify gate (`grep -c 'shell=True' backend/services/qa_pipeline.py`).
    Docstring mentions of the literal string "shell=True" in threat-mitigation prose are
    expected and not a violation — only live code (non-comment, non-docstring lines) matters.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "services", "qa_pipeline.py")
    with open(path) as f:
        lines = f.readlines()

    in_docstring = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            # Toggle docstring state; a line that both opens and closes a
            # one-line docstring doesn't change net state, so only toggle
            # when the triple-quote count on the line is odd.
            if stripped.count('"""') % 2 == 1 or stripped.count("'''") % 2 == 1:
                in_docstring = not in_docstring
            continue
        if in_docstring:
            continue
        if stripped.startswith("#"):
            continue
        assert "shell=True" not in line, f"shell=True found in live code: {line!r}"
