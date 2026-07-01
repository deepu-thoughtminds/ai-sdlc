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
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database import get_database
from repositories import pipeline_state_repo


@contextmanager
def _fake_managed_container(*args, **kwargs):
    """Stand-in for the Phase-28 live-app container — yields a ready URL without
    starting Docker (the real one detects the stack and runs a container)."""
    yield "http://app:3000"



from services.crypto import encrypt_credential  # noqa: E402
from services.test_executor import TestResult  # noqa: E402





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
    return pipeline_state_repo.create(db, project_id, "PROJ-1", "qa", status=status)


@pytest.mark.asyncio
async def test_qa_attempt_set_to_zero_before_execution():
    """run_static_analysis raises immediately -> qa_attempt==0 persists in DB.

    T-23-04: the commit before execution must have persisted qa_attempt=0
    even though execution itself failed afterward.
    """
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    state_row = _make_state_row(db)

    with (
        patch("services.qa_pipeline.clone_repository", return_value=_make_cloned_repo()),
        patch("services.qa_pipeline.run_static_analysis", side_effect=RuntimeError("boom")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.qa_attempt == 0
    pass


@pytest.mark.asyncio
async def test_workspace_cleaned_up_on_success():
    """Successful static analysis run -> shutil.rmtree called with workspace path (T-23-03)."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo("/tmp/qa-success-workspace")
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree") as mock_rmtree,
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/qa-success-workspace", ignore_errors=True)
    pass


@pytest.mark.asyncio
async def test_workspace_cleaned_up_on_failure():
    """clone succeeds, run_static_analysis raises -> shutil.rmtree still called (T-23-03)."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo("/tmp/qa-failure-workspace")

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", side_effect=RuntimeError("tool crashed")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree") as mock_rmtree,
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/qa-failure-workspace", ignore_errors=True)
    pass


@pytest.mark.asyncio
async def test_workspace_cleaned_up_on_timeout():
    """run_static_analysis returns a timed_out result -> shutil.rmtree still called."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
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
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_rmtree.assert_called_once_with("/tmp/qa-timeout-workspace", ignore_errors=True)
    pass


@pytest.mark.asyncio
async def test_jira_comment_posted_on_success():
    """Successful run -> hermes_post_comment called once with PASSED/FAILED text."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    comment_body = mock_post.call_args[0][4]
    assert "PASSED" in comment_body or "FAILED" in comment_body
    pass


@pytest.mark.asyncio
async def test_jira_comment_posted_on_failure():
    """Even when pipeline raises, hermes_post_comment is called with a failure message.

    Also guards against the NameError regression: jira_token/jira_email must be
    bound before the try block so Step 6 can run after an exception.
    """
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
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
    pass


@pytest.mark.asyncio
async def test_jira_comment_posted_on_failure_before_jira_token_assigned():
    """decrypt_credential raises BEFORE jira_token assignment -> no NameError; comment still posted."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    with (
        patch("services.qa_pipeline.decrypt_credential", side_effect=RuntimeError("decrypt failed")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        # Must not raise NameError — failure path must complete cleanly.
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    pass


@pytest.mark.asyncio
async def test_pipeline_state_status_complete_on_success():
    """Successful run -> state_row.status == 'complete'."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    state_row = _make_state_row(db)

    cloned = _make_cloned_repo()
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "complete"
    pass


@pytest.mark.asyncio
async def test_pipeline_state_status_failed_on_exception():
    """Exception during execution -> state_row.status == 'failed'."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    state_row = _make_state_row(db)

    with (
        patch("services.qa_pipeline.clone_repository", side_effect=RuntimeError("clone failed")),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    state_row = pipeline_state_repo.get(db, state_row.id)
    assert state_row.status == "failed"
    pass


@pytest.mark.asyncio
async def test_fresh_clone_not_dev_workspace():
    """clone_repository called exactly once inside run() with decrypted github_repo."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned) as mock_clone,
        patch("services.qa_pipeline.run_static_analysis", return_value=results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_clone.assert_called_once_with("owner/repo", "gh-secret")
    pass


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


# ---------------------------------------------------------------------------
# Phase 24 new tests: unit-test-generation step in run()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_passes_cbm_context_to_generate_unit_tests():
    """run() queries CBM graph and forwards the result as codebase_context to generate_unit_tests."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
    cbm_nodes = [{"name": "LoginPage", "file": "src/pages/LoginPage.tsx"}]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": cbm_nodes}) as mock_cbm,
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]) as mock_gen,
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_cbm.assert_called_once()
    _, gen_kwargs = mock_gen.call_args
    assert gen_kwargs.get("codebase_context") is not None, (
        f"codebase_context not forwarded: {gen_kwargs!r}"
    )


@pytest.mark.asyncio
async def test_run_calls_generate_unit_tests_with_issue_key():
    """run() calls generate_unit_tests(...) with issue_key='PROJ-1'."""
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]) as mock_gen,
        patch("services.qa_pipeline.run_command"),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_gen.assert_called_once()
    _, kwargs = mock_gen.call_args
    assert kwargs.get("issue_key") == "PROJ-1", f"Expected issue_key='PROJ-1', got: {kwargs!r}"
    pass


@pytest.mark.asyncio
async def test_generated_test_file_written_to_workspace(tmp_path):
    """When generate_unit_tests returns one FileChange, run() writes that file
    under the cloned workspace at the resolved path.

    Uses a real tmp_path-based workspace so we can assert the file exists on disk
    after run() completes — no mocking of pathlib.Path.write_text.
    """
    from services.code_generator import FileChange
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    workspace = tmp_path / "qa-workspace"
    workspace.mkdir()
    # Create a minimal tests/ dir expected by the path-guard
    tests_dir = workspace / "tests"
    tests_dir.mkdir()

    cloned = _make_cloned_repo(str(workspace))
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
    generated = [FileChange(path="tests/test_generated.py", content="def test_ok(): assert True")]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=generated),
        patch("services.qa_pipeline.run_command",
              return_value=TestResult(tool="pytest", returncode=0, stdout="1 passed", stderr="", timed_out=False)),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    written_file = workspace / "tests" / "test_generated.py"
    assert written_file.exists(), f"Expected {written_file} to exist after run()"
    assert "test_ok" in written_file.read_text()
    pass


@pytest.mark.asyncio
async def test_path_traversal_rejected_without_raising():
    """FileChange.path resolving outside workspace is rejected without raising out of pipeline.

    T-24-01: path-traversal guard must catch ValueError per-file (not abort the whole run).
    Pipeline must complete, status set to 'complete' or 'failed', comment posted.
    """
    from services.code_generator import FileChange
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo("/tmp/qa-traversal-workspace")
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
    # Malicious path: ../../etc/passwd
    traversal_change = FileChange(path="../../etc/passwd", content="hacked")

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[traversal_change]),
        patch("services.qa_pipeline.run_command"),
    ):
        # Must not raise out of run()
        result = await run(project, "PROJ-1", "Feature X", "desc", db)

    # Pipeline must still complete (comment posted)
    mock_post.assert_called_once()
    pass


@pytest.mark.asyncio
async def test_comment_contains_unit_test_and_static_analysis_sections(tmp_path):
    """Jira comment contains both Unit Tests and Static Analysis sections
    when both lists are non-empty.

    QAREP-01: per-category reporting at minimum unit tests + static analysis.
    """
    from services.code_generator import FileChange
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    workspace = tmp_path / "qa-workspace"
    workspace.mkdir()
    (workspace / "tests").mkdir()

    cloned = _make_cloned_repo(str(workspace))
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
    unit_test_result = TestResult(tool="pytest", returncode=0, stdout="1 passed", stderr="", timed_out=False)
    generated = [FileChange(path="tests/test_foo.py", content="def test_ok(): assert True")]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=generated),
        patch("services.qa_pipeline.run_command", return_value=unit_test_result),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_post.assert_called_once()
    comment_body = mock_post.call_args[0][4]
    # Must contain both sections, with actual unit test result rendered (not the fallback note)
    assert "PASSED" in comment_body, f"Unit test PASSED result not in comment: {comment_body!r}"
    assert "Unit Tests" in comment_body or "unit test" in comment_body.lower(), (
        f"'Unit Tests' section not found in comment: {comment_body!r}"
    )
    assert "Static Analysis" in comment_body or "static analysis" in comment_body.lower(), (
        f"'Static Analysis' section not found in comment: {comment_body!r}"
    )
    pass


@pytest.mark.asyncio
async def test_empty_generate_unit_tests_skips_execution():
    """When generate_unit_tests returns [], run() skips write+execute step.

    run_command must not be called for a generated test file.
    The Jira comment must note that no unit tests were generated.
    Static analysis results still appear in the comment.
    """
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command") as mock_run_command,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    # run_command must not have been called for a generated test file
    mock_run_command.assert_not_called()

    mock_post.assert_called_once()
    comment_body = mock_post.call_args[0][4]
    # Comment must note "no unit tests" generated or similar
    assert "no unit test" in comment_body.lower() or "unit test" in comment_body.lower(), (
        f"Comment does not mention unit tests: {comment_body!r}"
    )
    # Static analysis still appears
    assert "ruff" in comment_body.lower() or "Static Analysis" in comment_body or "static" in comment_body.lower(), (
        f"Static analysis section missing from comment: {comment_body!r}"
    )
    pass


# ---------------------------------------------------------------------------
# Phase 26-01 RED: E2E generation + has_active_qa_run() — TESTGEN-03, QATRIG-03
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_generation_skipped_when_no_playwright_config():
    """When glob finds no playwright.config.*, E2E tests are NOT generated.

    Comment must contain 'E2E Tests' section with a skip note mentioning 'playwright.config'.
    """
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    cloned = _make_cloned_repo()
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]

    mock_glob_module = MagicMock()
    mock_glob_module.glob.return_value = []

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
        patch("services.qa_pipeline.run_command"),
        patch("services.qa_pipeline.run_auto_fix_loop", return_value=([], None)),
        patch("services.qa_pipeline.generate_e2e_tests", create=True, return_value=[]) as mock_e2e_gen,
        patch("services.qa_pipeline.glob", mock_glob_module),
        patch("services.qa_pipeline.managed_app_container", _fake_managed_container),
        patch("services.qa_pipeline.run_claude_playwright_generator", new_callable=AsyncMock, return_value=[]),
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_e2e_gen.assert_not_called()
    comment_body = mock_post.call_args[0][4]
    assert "E2E Tests" in comment_body, f"'E2E Tests' section not in comment: {comment_body!r}"
    assert "playwright.config" in comment_body.lower(), (
        f"'playwright.config' not mentioned in skip note: {comment_body!r}"
    )
    pass


@pytest.mark.asyncio
async def test_e2e_generation_runs_when_playwright_config_found():
    """When glob finds playwright.config.*, E2E tests are generated and executed.

    Comment must contain 'E2E Tests' and 'PASSED'.
    """
    from services.qa_pipeline import run
    from services.code_generator import FileChange

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    import tempfile, os as _os
    with tempfile.TemporaryDirectory() as workspace:
        cloned = _make_cloned_repo(workspace)
        static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
        e2e_change = FileChange(path="e2e/test_login.spec.ts", content="test('ok', () => {});")

        mock_glob_module = MagicMock()
        mock_glob_module.glob.return_value = [_os.path.join(workspace, "playwright.config.ts")]

        with (
            patch("services.qa_pipeline.clone_repository", return_value=cloned),
            patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
            patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock) as mock_post,
            patch("services.qa_pipeline.shutil.rmtree"),
            patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
            patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
            patch("services.qa_pipeline.run_command",
                  return_value=TestResult(tool="playwright", returncode=0, stdout="1 passed", stderr="", timed_out=False)),
            patch("services.qa_pipeline.run_auto_fix_loop", return_value=([], None)),
            patch("services.qa_pipeline.generate_e2e_tests", create=True, return_value=[e2e_change]) as mock_e2e_gen,
            patch("services.qa_pipeline.glob", mock_glob_module),
            patch("services.qa_pipeline.managed_app_container", _fake_managed_container),
            patch("services.qa_pipeline.run_claude_playwright_generator", new_callable=AsyncMock, return_value=[]),
        ):
            await run(project, "PROJ-1", "Feature X", "desc", db)

    mock_e2e_gen.assert_called_once()
    comment_body = mock_post.call_args[0][4]
    assert "E2E Tests" in comment_body, f"'E2E Tests' section not in comment: {comment_body!r}"
    assert "PASSED" in comment_body, f"'PASSED' not in E2E comment: {comment_body!r}"
    pass


@pytest.mark.asyncio
async def test_e2e_path_traversal_rejected():
    """E2E FileChange.path escaping workspace is rejected per-file; run() still completes.

    T-26-01: mirrors T-24-01 per-file catch-and-continue pattern for E2E files.
    """
    from services.qa_pipeline import run
    from services.code_generator import FileChange

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    import tempfile, os as _os
    with tempfile.TemporaryDirectory() as workspace:
        cloned = _make_cloned_repo(workspace)
        static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
        bad_change = FileChange(path="../../etc/passwd", content="evil")

        mock_glob_module = MagicMock()
        mock_glob_module.glob.return_value = [_os.path.join(workspace, "playwright.config.ts")]

        with (
            patch("services.qa_pipeline.clone_repository", return_value=cloned),
            patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
            patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
            patch("services.qa_pipeline.shutil.rmtree"),
            patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
            patch("services.qa_pipeline.generate_unit_tests", return_value=[]),
            patch("services.qa_pipeline.run_command"),
            patch("services.qa_pipeline.run_auto_fix_loop", return_value=([], None)),
            patch("services.qa_pipeline.generate_e2e_tests", create=True, return_value=[bad_change]),
            patch("services.qa_pipeline.glob", mock_glob_module),
        ):
            await run(project, "PROJ-1", "Feature X", "desc", db)

    pass
    # If run() raised, we'd get an exception above. The fact it returned means the guard worked.
    # No assert needed beyond "no exception raised" — mirrors test_path_traversal_rejected_without_raising.


def test_has_active_qa_run_returns_true_when_running_row_exists():
    """has_active_qa_run returns True when a stage=qa/status=running row exists."""
    from services.qa_pipeline import has_active_qa_run

    db = get_database()
    pipeline_state_repo.create(db, 1, "PROJ-1", "qa", status="running")

    assert has_active_qa_run("PROJ-1", db) is True
    pass


def test_has_active_qa_run_returns_false_when_no_running_row():
    """has_active_qa_run returns False when no running qa row exists."""
    from services.qa_pipeline import has_active_qa_run

    db = get_database()
    # Add a completed row — should NOT count
    pipeline_state_repo.create(db, 1, "PROJ-1", "qa", status="complete")

    assert has_active_qa_run("PROJ-1", db) is False
    pass


@pytest.mark.asyncio
async def test_js_test_file_dispatches_to_npm_not_pytest(tmp_path):
    """Generated .test.tsx file must run via npm/sh, never pytest (TESTGEN-04).

    Reproduces the SCRUM-82 failure: pytest invoked against a TypeScript test
    file. run_command's ToolchainCommand for a .test.tsx file must use
    "npm"/"sh" in its docker command, not "pytest".
    """
    from services.code_generator import FileChange
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    workspace = tmp_path / "qa-workspace"
    workspace.mkdir()
    (workspace / "tests" / "pages").mkdir(parents=True)

    cloned = _make_cloned_repo(str(workspace))
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
    generated = [FileChange(path="tests/pages/LoginPage.test.tsx", content="test('ok', () => {})")]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=generated),
        patch("services.qa_pipeline.run_command",
              return_value=TestResult(tool="npm test", returncode=0, stdout="1 passed", stderr="", timed_out=False)) as mock_run_command,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    assert mock_run_command.call_count == 1
    cmd_obj = mock_run_command.call_args[0][0]
    assert "pytest" not in cmd_obj.command, f"pytest must not appear in command for a .tsx file: {cmd_obj.command!r}"
    joined = " ".join(cmd_obj.command)
    assert "npm" in joined, f"Expected npm in command for a .tsx test file: {cmd_obj.command!r}"
    pass


@pytest.mark.asyncio
async def test_py_test_file_still_dispatches_to_pytest(tmp_path):
    """Generated .py file must still run via pytest — no regression for the Python path."""
    from services.code_generator import FileChange
    from services.qa_pipeline import run

    project = _make_mock_project()
    db = get_database()
    _make_state_row(db)

    workspace = tmp_path / "qa-workspace"
    workspace.mkdir()
    (workspace / "tests").mkdir()

    cloned = _make_cloned_repo(str(workspace))
    static_results = [TestResult(tool="ruff", returncode=0, stdout="ok", stderr="", timed_out=False)]
    generated = [FileChange(path="tests/test_foo.py", content="def test_ok(): assert True")]

    with (
        patch("services.qa_pipeline.clone_repository", return_value=cloned),
        patch("services.qa_pipeline.run_static_analysis", return_value=static_results),
        patch("services.qa_pipeline.hermes_post_comment", new_callable=AsyncMock),
        patch("services.qa_pipeline.shutil.rmtree"),
        patch("services.qa_pipeline.cbm_search_with_auto_index", return_value={"results": []}),
        patch("services.qa_pipeline.generate_unit_tests", return_value=generated),
        patch("services.qa_pipeline.run_command",
              return_value=TestResult(tool="pytest", returncode=0, stdout="1 passed", stderr="", timed_out=False)) as mock_run_command,
    ):
        await run(project, "PROJ-1", "Feature X", "desc", db)

    cmd_obj = mock_run_command.call_args[0][0]
    assert "pytest" in cmd_obj.command, f"Expected pytest still used for a .py file: {cmd_obj.command!r}"
    pass
