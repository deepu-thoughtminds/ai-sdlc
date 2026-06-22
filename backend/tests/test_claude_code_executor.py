"""Unit tests for services.claude_code_executor.

Tests:
1. test_run_claude_code_executor_success — claude exits 0, git diff/ls-files report a
   changed file → FileChange returned with file content read from workspace.
2. test_run_claude_code_executor_cli_failure — claude exits non-zero → empty list.
3. test_run_claude_code_executor_no_diff — claude exits 0 but no diff/untracked files
   → empty list.

subprocess.run is patched in all tests — no real claude CLI invocation occurs.
"""

from unittest.mock import MagicMock, patch

from services.claude_code_executor import run_claude_code_executor


def _subprocess_result(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_run_claude_code_executor_success(tmp_path):
    """claude exits 0, git diff reports a file → FileChange with file content returned."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("def bar(): pass")

    def fake_run(cmd, **kwargs):
        if cmd[0] == "claude":
            return _subprocess_result(returncode=0)
        if cmd[:2] == ["git", "diff"]:
            return _subprocess_result(stdout="src/foo.py\n")
        if cmd[:2] == ["git", "ls-files"]:
            return _subprocess_result(stdout="")
        return _subprocess_result()

    with patch("services.claude_code_executor.subprocess.run", side_effect=fake_run):
        result = run_claude_code_executor(str(tmp_path), "PROJ-1", "summary", "desc", "arch")

    assert len(result) == 1
    assert result[0].path == "src/foo.py"
    assert result[0].content == "def bar(): pass"


def test_run_claude_code_executor_cli_failure(tmp_path):
    """claude CLI exits non-zero → empty list, no git commands attempted."""
    with patch(
        "services.claude_code_executor.subprocess.run",
        return_value=_subprocess_result(returncode=1, stderr="boom"),
    ) as mock_run:
        result = run_claude_code_executor(str(tmp_path), "PROJ-1", "summary", "desc", "arch")

    assert result == []
    mock_run.assert_called_once()


def test_run_claude_code_executor_no_diff(tmp_path):
    """claude exits 0 but git diff/ls-files report nothing → empty list."""

    def fake_run(cmd, **kwargs):
        if cmd[0] == "claude":
            return _subprocess_result(returncode=0)
        return _subprocess_result(stdout="")

    with patch("services.claude_code_executor.subprocess.run", side_effect=fake_run):
        result = run_claude_code_executor(str(tmp_path), "PROJ-1", "summary", "desc", "arch")

    assert result == []
