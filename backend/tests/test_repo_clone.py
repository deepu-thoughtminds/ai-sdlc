"""Unit tests for services.repo_clone — DEVPIPE-02.

Tests (5 total):
1. test_clone_repository_returns_cloned_repo — successful clone returns ClonedRepo
   with correct owner/repo and workspace_path that was the subprocess target dir.
2. test_clone_repository_nonzero_exit_raises — git returns exit code 1 → RuntimeError.
3. test_clone_repository_timeout_raises — subprocess.TimeoutExpired → RuntimeError.
4. test_clone_repository_invalid_slug_raises — malformed github_repo → ValueError.
5. test_clone_repository_token_not_in_log — ensure github_token never appears in
   any log.warning call during a failure.

All tests mock subprocess.run — no real git calls occur.
"""

import logging
import subprocess
from unittest.mock import MagicMock, call, patch

import pytest

from services.repo_clone import ClonedRepo, _parse_github_repo, clone_repository


# ---------------------------------------------------------------------------
# _parse_github_repo helpers
# ---------------------------------------------------------------------------


def test_parse_github_repo_valid():
    """Valid 'owner/repo' slug returns (owner, repo) tuple."""
    result = _parse_github_repo("acme/my-app")
    assert result == ("acme", "my-app")


def test_parse_github_repo_invalid_no_slash():
    """Slug without a slash returns None."""
    result = _parse_github_repo("noslash")
    assert result is None


def test_parse_github_repo_invalid_empty():
    """Empty string returns None."""
    result = _parse_github_repo("")
    assert result is None


def test_parse_github_repo_invalid_extra_slashes():
    """Three-segment path returns None (not an owner/repo slug)."""
    result = _parse_github_repo("owner/repo/extra")
    assert result is None


# ---------------------------------------------------------------------------
# clone_repository integration tests (subprocess mocked)
# ---------------------------------------------------------------------------


def _make_success_process(workspace_path: str = "/tmp/jarvis-workspace") -> MagicMock:
    """Return a mock CompletedProcess with returncode=0."""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = ""
    proc.stderr = ""
    return proc


def _make_failure_process(returncode: int = 1, stderr: str = "fatal: not found") -> MagicMock:
    """Return a mock CompletedProcess with a non-zero returncode."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = ""
    proc.stderr = stderr
    return proc


def test_clone_repository_returns_cloned_repo():
    """Successful subprocess.run → ClonedRepo with correct fields.

    Verifies:
    - Return type is ClonedRepo.
    - owner and repo are parsed from the slug.
    - workspace_path is a string (the temp dir path).
    - subprocess.run was called once with ['git', 'clone', ...].
    """
    with patch("subprocess.run", return_value=_make_success_process()) as mock_run, \
         patch("tempfile.mkdtemp", return_value="/tmp/jarvis-acme-my-app-abc"):

        result = clone_repository("acme/my-app", "ghp_test_token")

    assert isinstance(result, ClonedRepo)
    assert result.owner == "acme"
    assert result.repo == "my-app"
    assert result.workspace_path == "/tmp/jarvis-acme-my-app-abc"

    mock_run.assert_called_once()
    call_args = mock_run.call_args
    cmd = call_args[0][0]
    assert cmd[0] == "git"
    assert cmd[1] == "clone"
    # Token-embedded URL should be in the args (not shell=True)
    assert any("x-access-token:ghp_test_token" in arg for arg in cmd)


def test_clone_repository_nonzero_exit_raises():
    """git clone exit code 1 → RuntimeError (no exception swallowed)."""
    with patch("subprocess.run", return_value=_make_failure_process(returncode=1)), \
         patch("tempfile.mkdtemp", return_value="/tmp/jarvis-workspace"), \
         patch("shutil.rmtree"):  # suppress cleanup calls

        with pytest.raises(RuntimeError, match="git clone failed"):
            clone_repository("acme/my-app", "ghp_test_token")


def test_clone_repository_timeout_raises():
    """subprocess.TimeoutExpired → RuntimeError."""
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["git", "clone"], timeout=120),
    ), \
         patch("tempfile.mkdtemp", return_value="/tmp/jarvis-workspace"), \
         patch("shutil.rmtree"):

        with pytest.raises(RuntimeError, match="git clone timed out"):
            clone_repository("acme/my-app", "ghp_test_token")


def test_clone_repository_invalid_slug_raises():
    """Malformed github_repo slug → ValueError before any subprocess call."""
    with patch("subprocess.run") as mock_run:
        with pytest.raises(ValueError, match="Invalid github_repo slug"):
            clone_repository("not-a-valid-slug", "ghp_test_token")

    mock_run.assert_not_called()


def test_clone_repository_token_not_in_log(caplog):
    """github_token must never appear in any log message during failure.

    This test captures log output at WARNING level and asserts the literal
    token string does not appear — even when git returns an error containing
    the URL in stderr.
    """
    stderr_with_token = "fatal: repository 'https://x-access-token:ghp_secret@github.com/acme/my-app.git/' not found"

    with patch(
        "subprocess.run",
        return_value=_make_failure_process(returncode=128, stderr=stderr_with_token),
    ), \
         patch("tempfile.mkdtemp", return_value="/tmp/jarvis-workspace"), \
         patch("shutil.rmtree"), \
         caplog.at_level(logging.WARNING, logger="services.repo_clone"):

        with pytest.raises(RuntimeError):
            clone_repository("acme/my-app", "ghp_secret")

    # Assert the literal token never appears in any log record
    all_log_text = " ".join(record.getMessage() for record in caplog.records)
    assert "ghp_secret" not in all_log_text, (
        "GitHub token appeared in log output — T-05-01 violation"
    )
