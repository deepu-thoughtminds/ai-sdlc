"""TDD tests for dev_pipeline.run() — DEVPIPE-01, DEVPIPE-05.

Tests (6 total):
1. test_run_no_confluence_url — find_latest_architecture_url returns None → informative
   comment posted, state status="complete", apply_commit_push_and_open_pr NOT called.
2. test_run_success — Confluence URL found, codegen returns changes → clone/codegen/PR all
   called; comment contains PR url; state status="complete".
3. test_run_no_code_changes — codegen returns [] → apply_commit_push_and_open_pr NOT called;
   informative comment posted; state status="complete".
4. test_run_cleanup_on_pr_failure — apply_commit_push_and_open_pr raises → shutil.rmtree
   still called with the workspace path; state status="failed".
5. test_run_exception_sets_failed_status — exception in pipeline → state status="failed";
   failure notification comment posted via hermes_post_comment.
6. test_run_draft_content_contains_pr_url — PipelineState.draft_content after successful run
   is a plain string containing "PR ready" and the PR html_url, not JSON.

Uses StaticPool in-memory DB; unittest.mock.patch for all external dependencies.

T-16-05: generate_code_changes must NOT receive any token value — verified by inspecting args.
T-16-06: jira_token/github_token/confluence_token must NOT appear in log output.
T-16-07: shutil.rmtree always runs, verified in test_run_cleanup_on_pr_failure.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, call, patch

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
    p.confluence_url = "https://conf.example.com"
    p.confluence_email = "bot@example.com"
    p.confluence_token = encrypt_credential("conf-secret")
    p.github_token = encrypt_credential("gh-secret")
    p.github_repo = encrypt_credential("owner/repo")
    p.github_url = "https://github.com/owner/repo"
    return p


def _make_cloned_repo(path="/tmp/fake-workspace"):
    from services.repo_clone import ClonedRepo
    return ClonedRepo(workspace_path=path, owner="owner", repo="repo")


def _make_file_change():
    from services.code_generator import FileChange
    return FileChange(path="src/foo.py", content="print('hello')")


def _make_pull_request():
    from services.pr_creator import PullRequest
    return PullRequest(html_url="https://github.com/owner/repo/pull/42", number=42, branch="jarvis/PROJ-1")


@pytest.mark.asyncio
async def test_run_no_confluence_url():
    """No Confluence URL in comments → informative comment posted; state complete; no clone."""
    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="dev_pipeline", status="running"
    )
    db.add(state_row)
    db.commit()

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[]) as mock_get_comments,
        patch("services.dev_pipeline.find_latest_architecture_url", return_value=None),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.dev_pipeline.clone_repository") as mock_clone,
        patch("services.dev_pipeline.apply_commit_push_and_open_pr") as mock_pr,
    ):
        result = await __import__("services.dev_pipeline", fromlist=["run"]).run(
            project, "PROJ-1", "Feature X", "Some description", db
        )

    mock_clone.assert_not_called()
    mock_pr.assert_not_called()
    mock_post.assert_called_once()
    assert "No Confluence architecture page" in result
    assert "PROJ-1" in result

    db.refresh(state_row)
    assert state_row.status == "complete"
    db.close()


@pytest.mark.asyncio
async def test_run_success():
    """Confluence URL found, codegen returns changes → full pipeline; PR URL in comment."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="dev_pipeline", status="running"
    )
    db.add(state_row)
    db.commit()

    comments = [{"body": "Here is the arch: https://conf.example.com/wiki/spaces/PROJ/pages/12345"}]
    cloned = _make_cloned_repo()
    file_changes = [_make_file_change()]
    pr = _make_pull_request()
    codebase_summary = MagicMock(directory_tree="src/\nsrc/foo.py")

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=comments),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/12345"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="## Architecture\nUse FastAPI."),
        patch("services.dev_pipeline.get_codebase_summary", return_value=codebase_summary),
        patch("services.dev_pipeline.clone_repository", return_value=cloned),
        patch("services.dev_pipeline.generate_code_changes", return_value=file_changes) as mock_codegen,
        patch("services.dev_pipeline.apply_commit_push_and_open_pr", return_value=pr) as mock_pr,
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.dev_pipeline.shutil.rmtree") as mock_rmtree,
    ):
        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    mock_pr.assert_called_once()
    mock_post.assert_called_once()
    assert "PR ready" in result
    assert "https://github.com/owner/repo/pull/42" in result

    # T-16-05: tokens must NOT be in generate_code_changes args
    codegen_args = mock_codegen.call_args[0]
    for arg in codegen_args:
        assert "secret" not in str(arg).lower(), f"Token leaked into codegen args: {arg}"

    db.refresh(state_row)
    assert state_row.status == "complete"
    assert "PR ready" in state_row.draft_content
    db.close()


@pytest.mark.asyncio
async def test_run_no_code_changes():
    """Codegen returns [] → no PR; informative comment posted; state complete."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="dev_pipeline", status="running"
    )
    db.add(state_row)
    db.commit()

    cloned = _make_cloned_repo()
    codebase_summary = MagicMock(directory_tree="src/")

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[
            {"body": "https://conf.example.com/wiki/spaces/PROJ/pages/99"}
        ]),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/99"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="minimal content"),
        patch("services.dev_pipeline.get_codebase_summary", return_value=codebase_summary),
        patch("services.dev_pipeline.clone_repository", return_value=cloned),
        patch("services.dev_pipeline.generate_code_changes", return_value=[]),
        patch("services.dev_pipeline.apply_commit_push_and_open_pr") as mock_pr,
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.dev_pipeline.shutil.rmtree"),
    ):
        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    mock_pr.assert_not_called()
    mock_post.assert_called_once()
    assert "no file changes" in result.lower() or "no code changes" in result.lower() or "produced no" in result

    db.refresh(state_row)
    assert state_row.status == "complete"
    db.close()


@pytest.mark.asyncio
async def test_run_cleanup_on_pr_failure():
    """apply_commit_push_and_open_pr raises → shutil.rmtree still called; state failed."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="dev_pipeline", status="running"
    )
    db.add(state_row)
    db.commit()

    cloned = _make_cloned_repo("/tmp/test-workspace-cleanup")
    codebase_summary = MagicMock(directory_tree="")

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[
            {"body": "https://conf.example.com/wiki/spaces/PROJ/pages/77"}
        ]),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/77"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="arch content"),
        patch("services.dev_pipeline.get_codebase_summary", return_value=codebase_summary),
        patch("services.dev_pipeline.clone_repository", return_value=cloned),
        patch("services.dev_pipeline.generate_code_changes", return_value=[_make_file_change()]),
        patch("services.dev_pipeline.apply_commit_push_and_open_pr",
              side_effect=RuntimeError("push failed")),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.dev_pipeline.shutil.rmtree") as mock_rmtree,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/test-workspace-cleanup", ignore_errors=True)

    db.refresh(state_row)
    assert state_row.status == "failed"
    db.close()


@pytest.mark.asyncio
async def test_run_exception_sets_failed_status():
    """Exception in pipeline → state status="failed"; failure notification posted."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="dev_pipeline", status="running"
    )
    db.add(state_row)
    db.commit()

    with (
        patch("services.dev_pipeline.get_comments",
              new_callable=AsyncMock, side_effect=RuntimeError("jira api down")),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    call_body = mock_post.call_args[0][4]
    assert "failed" in call_body.lower() or "Dev pipeline failed" in call_body

    db.refresh(state_row)
    assert state_row.status == "failed"
    db.close()


@pytest.mark.asyncio
async def test_run_draft_content_contains_pr_url():
    """PipelineState.draft_content after success is a string with 'PR ready' and the URL."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = TestingSession()

    state_row = PipelineState(
        project_id=1, ticket_key="PROJ-1", stage="dev_pipeline", status="running"
    )
    db.add(state_row)
    db.commit()

    pr = _make_pull_request()
    codebase_summary = MagicMock(directory_tree="")

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[
            {"body": "https://conf.example.com/wiki/spaces/PROJ/pages/1"}
        ]),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="content"),
        patch("services.dev_pipeline.get_codebase_summary", return_value=codebase_summary),
        patch("services.dev_pipeline.clone_repository", return_value=_make_cloned_repo()),
        patch("services.dev_pipeline.generate_code_changes", return_value=[_make_file_change()]),
        patch("services.dev_pipeline.apply_commit_push_and_open_pr", return_value=pr),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.dev_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    db.refresh(state_row)
    assert isinstance(state_row.draft_content, str)
    assert not state_row.draft_content.startswith("{")
    assert "PR ready" in state_row.draft_content
    assert pr.html_url in state_row.draft_content
    db.close()
