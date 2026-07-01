"""TDD tests for dev_pipeline.run() — DEVPIPE-01, DEVPIPE-05.

Tests:
1. test_run_no_confluence_url — find_latest_architecture_url returns None → informative
   comment posted, state status="complete", apply_commit_push_and_open_pr NOT called.
2. test_run_success — Confluence URL found, codegen returns changes → full pipeline;
   PR URL in comment; state status="complete".
3. test_run_no_code_changes — codegen returns [] → apply_commit_push_and_open_pr NOT called;
   informative comment posted; state status="complete".
4. test_run_cleanup_on_pr_failure — apply_commit_push_and_open_pr raises → shutil.rmtree
   still called with the workspace path; state status="failed".
5. test_run_exception_sets_failed_status — exception in pipeline → state status="failed";
   failure notification comment posted via hermes_post_comment.
6. test_run_draft_content_contains_pr_url — PipelineState.draft_content after successful run
   is a plain string containing "PR ready" and the PR html_url, not JSON.
7. test_run_uses_cbm_graph_context — _query_dev_context is called with issue_key and
   issue_summary; its return value is forwarded to run_agentic_codegen as codebase_context.
8. test_read_relevant_files_keyword_match — files containing keywords are returned.
9. test_read_relevant_files_cap — total chars across all returned files <= 8000.

Uses StaticPool in-memory DB; unittest.mock.patch for all external dependencies.

T-16-05: run_agentic_codegen must NOT receive any token value — verified by inspecting args.
T-16-06: jira_token/github_token/confluence_token must NOT appear in log output.
T-16-07: shutil.rmtree always runs, verified in test_run_cleanup_on_pr_failure.
"""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from database import get_database
from repositories import pipeline_state_repo



from services.crypto import encrypt_credential  # noqa: E402





@pytest.fixture(autouse=True)
def clear_claude_api_key():
    """Ensure CLAUDE_API_KEY is unset by default so existing tests exercise the
    freellmapi (generate_code_changes) path. Routing tests set it explicitly."""
    os.environ.pop("CLAUDE_API_KEY", None)
    yield
    os.environ.pop("CLAUDE_API_KEY", None)


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
    db = get_database()

    state_row = pipeline_state_repo.create(db, 1, "PROJ-1", "dev_pipeline", status="running")

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

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "complete"
    pass


@pytest.mark.asyncio
async def test_run_success():
    """Confluence URL found, codegen returns changes → full pipeline; PR URL in comment."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = get_database()

    state_row = pipeline_state_repo.create(db, 1, "PROJ-1", "dev_pipeline", status="running")

    comments = [{"body": "Here is the arch: https://conf.example.com/wiki/spaces/PROJ/pages/12345"}]
    cloned = _make_cloned_repo()
    file_changes = [_make_file_change()]
    pr = _make_pull_request()
    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=comments),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/12345"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="## Architecture\nUse FastAPI."),
        patch("services.dev_pipeline._query_dev_context", new_callable=AsyncMock, return_value="src/\nsrc/foo.py"),
        patch("services.dev_pipeline.clone_repository", return_value=cloned),
        patch("services.dev_pipeline.read_relevant_files", return_value={"src/foo.py": "x"}) as mock_relfiles,
        patch("services.dev_pipeline.run_agentic_codegen", new_callable=AsyncMock, return_value=file_changes) as mock_codegen,
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

    # read_relevant_files is still invoked to gather context
    mock_relfiles.assert_called_once()

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "complete"
    assert "PR ready" in state_row.draft_content
    pass


@pytest.mark.asyncio
async def test_run_no_code_changes():
    """Codegen returns [] → no PR; informative comment posted; state complete."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = get_database()

    state_row = pipeline_state_repo.create(db, 1, "PROJ-1", "dev_pipeline", status="running")

    cloned = _make_cloned_repo()

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[
            {"body": "https://conf.example.com/wiki/spaces/PROJ/pages/99"}
        ]),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/99"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="minimal content"),
        patch("services.dev_pipeline._query_dev_context", new_callable=AsyncMock, return_value="src/"),
        patch("services.dev_pipeline.clone_repository", return_value=cloned),
        patch("services.dev_pipeline.run_agentic_codegen", new_callable=AsyncMock, return_value=[]),
        patch("services.dev_pipeline.apply_commit_push_and_open_pr") as mock_pr,
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.dev_pipeline.shutil.rmtree"),
    ):
        result = await run(project, "PROJ-1", "Feature X", "Some description", db)

    mock_pr.assert_not_called()
    mock_post.assert_called_once()
    assert "no file changes" in result.lower() or "no code changes" in result.lower() or "produced no" in result

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "complete"
    pass


@pytest.mark.asyncio
async def test_run_cleanup_on_pr_failure():
    """apply_commit_push_and_open_pr raises → shutil.rmtree still called; state failed."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = get_database()

    state_row = pipeline_state_repo.create(db, 1, "PROJ-1", "dev_pipeline", status="running")

    cloned = _make_cloned_repo("/tmp/test-workspace-cleanup")

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[
            {"body": "https://conf.example.com/wiki/spaces/PROJ/pages/77"}
        ]),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/77"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="arch content"),
        patch("services.dev_pipeline._query_dev_context", new_callable=AsyncMock, return_value=""),
        patch("services.dev_pipeline.clone_repository", return_value=cloned),
        patch("services.dev_pipeline.run_agentic_codegen", new_callable=AsyncMock, return_value=[_make_file_change()]),
        patch("services.dev_pipeline.apply_commit_push_and_open_pr",
              side_effect=RuntimeError("push failed")),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.dev_pipeline.shutil.rmtree") as mock_rmtree,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/test-workspace-cleanup", ignore_errors=True)

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "failed"
    pass


@pytest.mark.asyncio
async def test_run_exception_sets_failed_status():
    """Exception in pipeline → state status="failed"; failure notification posted."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = get_database()

    state_row = pipeline_state_repo.create(db, 1, "PROJ-1", "dev_pipeline", status="running")

    with (
        patch("services.dev_pipeline.get_comments",
              new_callable=AsyncMock, side_effect=RuntimeError("jira api down")),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    call_body = mock_post.call_args[0][4]
    assert "failed" in call_body.lower() or "Dev pipeline failed" in call_body

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "failed"
    pass


@pytest.mark.asyncio
async def test_run_draft_content_contains_pr_url():
    """PipelineState.draft_content after success is a string with 'PR ready' and the URL."""
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = get_database()

    state_row = pipeline_state_repo.create(db, 1, "PROJ-1", "dev_pipeline", status="running")

    pr = _make_pull_request()

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[
            {"body": "https://conf.example.com/wiki/spaces/PROJ/pages/1"}
        ]),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="content"),
        patch("services.dev_pipeline._query_dev_context", new_callable=AsyncMock, return_value=""),
        patch("services.dev_pipeline.clone_repository", return_value=_make_cloned_repo()),
        patch("services.dev_pipeline.run_agentic_codegen", new_callable=AsyncMock, return_value=[_make_file_change()]),
        patch("services.dev_pipeline.apply_commit_push_and_open_pr", return_value=pr),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.dev_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert isinstance(state_row.draft_content, str)
    assert not state_row.draft_content.startswith("{")
    assert "PR ready" in state_row.draft_content
    assert pr.html_url in state_row.draft_content
    pass


@pytest.mark.asyncio
async def test_run_uses_cbm_graph_context():
    """_query_dev_context is called with issue_key+issue_summary; return value forwarded to codegen.

    Replaces the old github_url/get_codebase_summary test — the pipeline no longer uses
    GitHub snapshots; it queries the codebase-memory-mcp graph instead.
    """
    from services.dev_pipeline import run

    project = _make_mock_project()
    db = get_database()
    state_row = pipeline_state_repo.create(db, 1, "PROJ-1", "dev_pipeline", status="running")

    pr = _make_pull_request()
    graph_text = "src/pages/LoginPage.tsx\nsrc/App.tsx"

    with (
        patch("services.dev_pipeline.get_comments", new_callable=AsyncMock, return_value=[
            {"body": "https://conf.example.com/wiki/spaces/PROJ/pages/1"}
        ]),
        patch("services.dev_pipeline.find_latest_architecture_url",
              return_value="https://conf.example.com/wiki/spaces/PROJ/pages/1"),
        patch("services.dev_pipeline.get_confluence_page_content",
              new_callable=AsyncMock, return_value="content"),
        patch("services.dev_pipeline._query_dev_context",
              new_callable=AsyncMock, return_value=graph_text) as mock_query,
        patch("services.dev_pipeline.clone_repository", return_value=_make_cloned_repo()),
        patch("services.dev_pipeline.run_agentic_codegen", new_callable=AsyncMock,
              return_value=[_make_file_change()]) as mock_codegen,
        patch("services.dev_pipeline.apply_commit_push_and_open_pr", return_value=pr),
        patch("services.dev_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.dev_pipeline.shutil.rmtree"),
    ):
        result = await run(project, "PROJ-1", "Feature X", "desc", db)

    # _query_dev_context must be called with issue_key and issue_summary
    mock_query.assert_called_once_with("PROJ-1", "Feature X")

    # graph_text must reach run_agentic_codegen as the codebase_context positional arg (index 5)
    mock_codegen.assert_called_once()
    codegen_codebase_arg = mock_codegen.call_args[0][5]
    assert "LoginPage.tsx" in codegen_codebase_arg, (
        f"graph_text must be forwarded to run_agentic_codegen as codebase_context, got: {codegen_codebase_arg!r}"
    )

    assert "PR ready" in result
    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "complete"


def test_read_relevant_files_keyword_match(tmp_path):
    """Only files whose content matches an issue keyword are returned."""
    from services.dev_pipeline import read_relevant_files

    (tmp_path / "matching.py").write_text("def login_feature():\n    pass\n")
    (tmp_path / "unrelated.txt").write_text("hello world\n")

    result = read_relevant_files(str(tmp_path), "login feature", "implement login flow")

    assert "matching.py" in result
    assert "unrelated.txt" not in result


def test_read_relevant_files_cap(tmp_path):
    """Total characters across all returned files do not exceed 8000."""
    from services.dev_pipeline import read_relevant_files

    (tmp_path / "big1.py").write_text("login " * 2000)
    (tmp_path / "big2.py").write_text("login " * 2000)

    result = read_relevant_files(str(tmp_path), "login", "")

    total_chars = sum(len(v) for v in result.values())
    assert total_chars <= 8000
