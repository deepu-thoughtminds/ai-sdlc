"""Tests for auto_fix_loop.py — AUTOFIX-01, AUTOFIX-02, AUTOFIX-03.

Module under test does not exist yet; all tests fail with ImportError until
Task 2 creates backend/services/auto_fix_loop.py (TDD RED).
"""

from unittest.mock import MagicMock, patch

import pytest
from services.code_generator import FileChange
from services.llm_router import LLMResponse
from services.test_executor import TestResult

from services.auto_fix_loop import MAX_ATTEMPTS, run_auto_fix_loop


def _make_test_result(tool, returncode, stdout="", stderr="", timed_out=False):
    return TestResult(
        tool=tool, returncode=returncode, stdout=stdout, stderr=stderr, timed_out=timed_out
    )


def _make_llm_response(content):
    return LLMResponse(provider="freellmapi", content=content, model="auto")


def test_run_auto_fix_loop_no_failures_returns_unchanged():
    results = [_make_test_result("pytest", 0, stdout="1 passed")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()

    with patch("services.auto_fix_loop.route_request") as mock_route, patch(
        "services.auto_fix_loop.apply_commit_push_and_open_pr"
    ) as mock_pr:
        updated, pr_url = run_auto_fix_loop(
            results, "/tmp/ws", "PROJ-1", "owner/repo", "tok", state_row, db
        )

    assert updated == results
    assert pr_url is None
    mock_route.assert_not_called()
    mock_pr.assert_not_called()


def test_run_auto_fix_loop_calls_route_request_autofix_stage():
    results = [_make_test_result("pytest", 1, stdout="FAIL output", stderr="AssertionError")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    passing = [_make_test_result("pytest", 0, stdout="1 passed")]

    with patch(
        "services.auto_fix_loop.route_request", return_value=_make_llm_response("[stub]")
    ) as mock_route, patch(
        "services.auto_fix_loop._parse_file_changes", return_value=[]
    ), patch(
        "services.auto_fix_loop._rerun_failing_tests", return_value=passing
    ), patch(
        "services.auto_fix_loop.apply_commit_push_and_open_pr"
    ):
        run_auto_fix_loop(results, "/tmp/ws", "PROJ-1", "owner/repo", "tok", state_row, db)

    mock_route.assert_called_once()
    args, kwargs = mock_route.call_args
    stage = kwargs.get("stage", args[0] if args else None)
    prompt = kwargs.get("prompt", args[1] if len(args) > 1 else None)
    assert stage == "autofix"
    assert "pytest" in prompt
    assert "FAIL output" in prompt
    assert "AssertionError" in prompt


def test_run_auto_fix_loop_prompt_truncates_at_2000():
    results = [_make_test_result("pytest", 1, stdout="A" * 3000, stderr="B" * 3000)]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    passing = [_make_test_result("pytest", 0)]
    captured_prompt = {}

    def _capture_route(*args, **kwargs):
        captured_prompt["prompt"] = kwargs.get("prompt", args[1] if len(args) > 1 else None)
        return _make_llm_response("[stub]")

    with patch("services.auto_fix_loop.route_request", side_effect=_capture_route), patch(
        "services.auto_fix_loop._parse_file_changes", return_value=[]
    ), patch("services.auto_fix_loop._rerun_failing_tests", return_value=passing), patch(
        "services.auto_fix_loop.apply_commit_push_and_open_pr"
    ):
        run_auto_fix_loop(results, "/tmp/ws", "PROJ-1", "owner/repo", "tok", state_row, db)

    prompt = captured_prompt["prompt"]
    assert "A" * 2000 in prompt
    assert "A" * 2001 not in prompt
    assert "B" * 2000 in prompt
    assert "B" * 2001 not in prompt


def test_run_auto_fix_loop_non_progress_detection_terminates_early():
    results = [_make_test_result("pytest", 1, stdout="same", stderr="same-err")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    fix = [FileChange(path="src/foo.py", content="fixed")]

    with patch(
        "services.auto_fix_loop.route_request", return_value=_make_llm_response("...")
    ) as mock_route, patch(
        "services.auto_fix_loop._parse_file_changes", return_value=fix
    ), patch(
        "services.auto_fix_loop._rerun_failing_tests", return_value=results
    ), patch(
        "services.auto_fix_loop.apply_commit_push_and_open_pr",
        return_value=MagicMock(html_url="https://github.com/test"),
    ):
        run_auto_fix_loop(results, "/tmp/ws", "PROJ-1", "owner/repo", "tok", state_row, db)

    assert mock_route.call_count <= 2


def test_run_auto_fix_loop_rejects_test_file_paths():
    results = [_make_test_result("pytest", 1, stdout="x", stderr="y")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    passing = [_make_test_result("pytest", 0)]
    bad_change = [FileChange(path="tests/test_foo.py", content="x")]

    with patch(
        "services.auto_fix_loop.route_request", return_value=_make_llm_response("...")
    ), patch("services.auto_fix_loop._parse_file_changes", return_value=bad_change), patch(
        "services.auto_fix_loop._rerun_failing_tests", return_value=passing
    ), patch("services.auto_fix_loop.apply_commit_push_and_open_pr") as mock_pr:
        run_auto_fix_loop(results, "/tmp/ws", "PROJ-1", "owner/repo", "tok", state_row, db)

    mock_pr.assert_not_called()


def test_run_auto_fix_loop_rejects_path_traversal():
    results = [_make_test_result("pytest", 1, stdout="x", stderr="y")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    passing = [_make_test_result("pytest", 0)]
    bad_change = [FileChange(path="../../etc/passwd", content="x")]

    with patch(
        "services.auto_fix_loop.route_request", return_value=_make_llm_response("...")
    ), patch("services.auto_fix_loop._parse_file_changes", return_value=bad_change), patch(
        "services.auto_fix_loop._rerun_failing_tests", return_value=passing
    ), patch("services.auto_fix_loop.apply_commit_push_and_open_pr") as mock_pr:
        updated, pr_url = run_auto_fix_loop(
            results, "/tmp/workspace", "PROJ-1", "owner/repo", "tok", state_row, db
        )

    mock_pr.assert_not_called()
    assert pr_url is None


def test_run_auto_fix_loop_opens_pr_on_applied_fix(tmp_path):
    results = [_make_test_result("pytest", 1, stdout="x", stderr="y")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    passing = [_make_test_result("pytest", 0)]
    fix = [FileChange(path="src/foo.py", content="fixed")]

    with patch(
        "services.auto_fix_loop.route_request", return_value=_make_llm_response("...")
    ), patch("services.auto_fix_loop._parse_file_changes", return_value=fix), patch(
        "services.auto_fix_loop._rerun_failing_tests", return_value=passing
    ), patch(
        "services.auto_fix_loop.apply_commit_push_and_open_pr",
        return_value=MagicMock(html_url="https://github.com/pr/1"),
    ) as mock_pr:
        updated, pr_url = run_auto_fix_loop(
            results, str(tmp_path), "PROJ-1", "owner/repo", "tok", state_row, db
        )

    assert pr_url == "https://github.com/pr/1"
    _, kwargs = mock_pr.call_args
    assert kwargs.get("branch_name") == "jarvis/qa-fix-PROJ-1"


def test_run_auto_fix_loop_stub_response_no_pr():
    results = [_make_test_result("pytest", 1, stdout="x", stderr="y")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    still_failing = [_make_test_result("pytest", 1, stdout="x", stderr="y2")]

    with patch(
        "services.auto_fix_loop.route_request", return_value=_make_llm_response("[stub]")
    ), patch("services.auto_fix_loop._parse_file_changes", return_value=[]), patch(
        "services.auto_fix_loop._rerun_failing_tests", return_value=still_failing
    ), patch("services.auto_fix_loop.apply_commit_push_and_open_pr") as mock_pr:
        run_auto_fix_loop(results, "/tmp/ws", "PROJ-1", "owner/repo", "tok", state_row, db)

    mock_pr.assert_not_called()


def test_run_auto_fix_loop_increments_qa_attempt():
    results = [_make_test_result("pytest", 1, stdout="x", stderr="y")]
    state_row = MagicMock(qa_attempt=0)
    db = MagicMock()
    # Always different stderr per call so fingerprint never repeats and all 3 attempts run.
    side_effects = [
        [_make_test_result("pytest", 1, stdout="x", stderr=f"y{i}")] for i in range(5)
    ]

    with patch(
        "services.auto_fix_loop.route_request", return_value=_make_llm_response("[stub]")
    ), patch("services.auto_fix_loop._parse_file_changes", return_value=[]), patch(
        "services.auto_fix_loop._rerun_failing_tests", side_effect=side_effects
    ), patch("services.auto_fix_loop.apply_commit_push_and_open_pr"), patch(
        "services.auto_fix_loop.pipeline_state_repo.update"
    ) as mock_update:
        run_auto_fix_loop(results, "/tmp/ws", "PROJ-1", "owner/repo", "tok", state_row, db)

    assert state_row.qa_attempt == 3
    # qa_attempt now persisted via the repository (Mongo) rather than db.commit()
    assert mock_update.call_count >= 3


def test_run_auto_fix_loop_max_attempts_constant():
    assert MAX_ATTEMPTS == 3
