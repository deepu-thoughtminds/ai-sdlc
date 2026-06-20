"""Unit tests for services.pr_creator — DEVPIPE-04.

Tests (7 total):
1. test_apply_commit_push_and_open_pr_success — mock subprocess.run (git ops) + respx
   (GitHub PR API); asserts PullRequest returned with correct html_url and branch.
2. test_branch_name_uses_jarvis_convention — asserts branch = "jarvis/issue-{key}".
3. test_git_config_set_before_commit — asserts git config calls precede commit.
4. test_github_api_pr_payload — asserts POST to /pulls with head, base, title fields.
5. test_nonzero_exit_raises — git checkout fails → RuntimeError propagated.
6. test_github_api_failure_raises — GitHub API returns 422 → RuntimeError.
7. test_token_not_logged_on_git_failure — token must not appear in log output.

subprocess.run is mocked for git commands; respx mocks the GitHub REST API.
No real git operations or network calls occur.
"""

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import httpx
import pytest
import respx

from services.pr_creator import PullRequest, apply_commit_push_and_open_pr
from services.code_generator import FileChange


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GITHUB_REPO = "acme/my-app"
GITHUB_TOKEN = "ghp_TEST_TOKEN"
ISSUE_KEY = "PROJ-42"
PR_URL = "https://github.com/acme/my-app/pull/7"

GITHUB_API_BASE = "https://api.github.com"


def _make_git_success() -> MagicMock:
    """Return a mock CompletedProcess with returncode=0."""
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = ""
    proc.stderr = ""
    return proc


def _make_git_failure(returncode: int = 1, stderr: str = "error") -> MagicMock:
    """Return a mock CompletedProcess with non-zero returncode."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = ""
    proc.stderr = stderr
    return proc


def _make_pr_api_response(
    html_url: str = PR_URL,
    number: int = 7,
) -> dict:
    """Build a minimal GitHub PR API response payload."""
    return {
        "html_url": html_url,
        "number": number,
        "head": {"ref": f"jarvis/issue-{ISSUE_KEY}"},
        "base": {"ref": "main"},
        "title": f"feat: Jarvis autonomous changes for {ISSUE_KEY}",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@respx.mock
def test_apply_commit_push_and_open_pr_success(tmp_path):
    """Mock git ops + GitHub API → PullRequest returned with correct fields."""
    os.environ.setdefault("GITHUB_API_BASE", GITHUB_API_BASE)

    # Mock GitHub PR creation endpoint
    respx.post(f"{GITHUB_API_BASE}/repos/acme/my-app/pulls").mock(
        return_value=httpx.Response(201, json=_make_pr_api_response())
    )

    file_changes = [
        FileChange(path="src/hello.py", content='print("hello")\n'),
    ]

    with patch("subprocess.run", return_value=_make_git_success()):
        result = apply_commit_push_and_open_pr(
            workspace_path=str(tmp_path),
            github_repo=GITHUB_REPO,
            github_token=GITHUB_TOKEN,
            issue_key=ISSUE_KEY,
            file_changes=file_changes,
        )

    assert isinstance(result, PullRequest)
    assert result.html_url == PR_URL
    assert result.number == 7
    assert result.branch == f"jarvis/issue-{ISSUE_KEY}"


@respx.mock
def test_branch_name_uses_jarvis_convention(tmp_path):
    """Branch name must follow jarvis/issue-{key} convention — DEVPIPE-04."""
    respx.post(f"{GITHUB_API_BASE}/repos/acme/my-app/pulls").mock(
        return_value=httpx.Response(201, json=_make_pr_api_response())
    )

    with patch("subprocess.run", return_value=_make_git_success()) as mock_run:
        result = apply_commit_push_and_open_pr(
            workspace_path=str(tmp_path),
            github_repo=GITHUB_REPO,
            github_token=GITHUB_TOKEN,
            issue_key=ISSUE_KEY,
            file_changes=[],
        )

    assert result.branch == "jarvis/issue-PROJ-42"

    # Verify the checkout command used the correct branch name
    all_calls = [c[0][0] for c in mock_run.call_args_list]
    branch_calls = [c for c in all_calls if "checkout" in c]
    assert any("jarvis/issue-PROJ-42" in c for c in branch_calls)


@respx.mock
def test_git_config_set_before_commit(tmp_path):
    """git config must be called before git commit in the call sequence."""
    respx.post(f"{GITHUB_API_BASE}/repos/acme/my-app/pulls").mock(
        return_value=httpx.Response(201, json=_make_pr_api_response())
    )

    with patch("subprocess.run", return_value=_make_git_success()) as mock_run:
        apply_commit_push_and_open_pr(
            workspace_path=str(tmp_path),
            github_repo=GITHUB_REPO,
            github_token=GITHUB_TOKEN,
            issue_key=ISSUE_KEY,
            file_changes=[],
        )

    all_cmds = [c[0][0] for c in mock_run.call_args_list]
    config_idx = next(
        (i for i, cmd in enumerate(all_cmds) if "config" in cmd), None
    )
    commit_idx = next(
        (i for i, cmd in enumerate(all_cmds) if "commit" in cmd), None
    )

    assert config_idx is not None, "git config not called"
    assert commit_idx is not None, "git commit not called"
    assert config_idx < commit_idx, "git config must precede git commit"


@respx.mock
def test_github_api_pr_payload(tmp_path):
    """GitHub PR API POST payload must include head, base, and title fields."""
    captured_requests = []

    def capture(request, route):
        captured_requests.append(request)
        return httpx.Response(201, json=_make_pr_api_response())

    respx.post(f"{GITHUB_API_BASE}/repos/acme/my-app/pulls").mock(side_effect=capture)

    with patch("subprocess.run", return_value=_make_git_success()):
        apply_commit_push_and_open_pr(
            workspace_path=str(tmp_path),
            github_repo=GITHUB_REPO,
            github_token=GITHUB_TOKEN,
            issue_key=ISSUE_KEY,
            file_changes=[],
            pr_title="Custom PR title",
        )

    assert captured_requests, "GitHub PR API was not called"
    request = captured_requests[0]
    import json as _json
    payload = _json.loads(request.content)

    assert payload["head"] == f"jarvis/issue-{ISSUE_KEY}"
    assert payload["base"] == "main"
    assert payload["title"] == "Custom PR title"


def test_nonzero_exit_raises(tmp_path):
    """git checkout fails → RuntimeError raised (no swallowing)."""
    with patch(
        "subprocess.run",
        return_value=_make_git_failure(returncode=128, stderr="fatal: branch exists"),
    ):
        with pytest.raises(RuntimeError, match="git"):
            apply_commit_push_and_open_pr(
                workspace_path=str(tmp_path),
                github_repo=GITHUB_REPO,
                github_token=GITHUB_TOKEN,
                issue_key=ISSUE_KEY,
                file_changes=[],
            )


@respx.mock
def test_github_api_failure_raises(tmp_path):
    """GitHub API returns 422 Unprocessable Entity → RuntimeError."""
    respx.post(f"{GITHUB_API_BASE}/repos/acme/my-app/pulls").mock(
        return_value=httpx.Response(422, json={"message": "Validation Failed"})
    )

    with patch("subprocess.run", return_value=_make_git_success()):
        with pytest.raises(RuntimeError, match="PR creation failed|HTTP 422"):
            apply_commit_push_and_open_pr(
                workspace_path=str(tmp_path),
                github_repo=GITHUB_REPO,
                github_token=GITHUB_TOKEN,
                issue_key=ISSUE_KEY,
                file_changes=[],
            )


def test_invalid_repo_slug_raises(tmp_path):
    """Malformed github_repo slug → ValueError before any git operation."""
    with patch("subprocess.run") as mock_run:
        with pytest.raises(ValueError, match="Invalid github_repo slug"):
            apply_commit_push_and_open_pr(
                workspace_path=str(tmp_path),
                github_repo="not-a-slug",
                github_token=GITHUB_TOKEN,
                issue_key=ISSUE_KEY,
                file_changes=[],
            )

    mock_run.assert_not_called()


def test_token_not_logged_on_git_failure(tmp_path, caplog):
    """T-07-01: github_token must not appear in any log output on git failure.

    Simulates a stderr from git that would naturally include the authenticated
    URL (which contains the token), then verifies log output is scrubbed.
    """
    stderr_with_token = (
        f"fatal: unable to access 'https://x-access-token:{GITHUB_TOKEN}@github.com/acme/my-app.git/': "
        "Failed to connect"
    )

    with patch(
        "subprocess.run",
        return_value=_make_git_failure(returncode=128, stderr=stderr_with_token),
    ), \
         caplog.at_level(logging.WARNING, logger="services.pr_creator"):

        with pytest.raises(RuntimeError):
            apply_commit_push_and_open_pr(
                workspace_path=str(tmp_path),
                github_repo=GITHUB_REPO,
                github_token=GITHUB_TOKEN,
                issue_key=ISSUE_KEY,
                file_changes=[],
            )

    all_log_text = " ".join(record.getMessage() for record in caplog.records)
    assert GITHUB_TOKEN not in all_log_text, (
        "GitHub token appeared in log output — T-07-01 violation"
    )
