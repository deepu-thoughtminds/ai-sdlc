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
            file_changes=[FileChange(path="src/hello.py", content="print(123)")],
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
            file_changes=[FileChange(path="src/hello.py", content="print(123)")],
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
            file_changes=[FileChange(path="src/hello.py", content="print(123)")],
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
                file_changes=[FileChange(path="src/hello.py", content="print(123)")],
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
                file_changes=[FileChange(path="src/hello.py", content="print(123)")],
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
                file_changes=[FileChange(path="src/hello.py", content="print(123)")],
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
                file_changes=[FileChange(path="src/hello.py", content="print(123)")],
            )

    all_log_text = " ".join(record.getMessage() for record in caplog.records)
    assert GITHUB_TOKEN not in all_log_text, (
        "GitHub token appeared in log output — T-07-01 violation"
    )


@respx.mock
def test_repeated_push_same_workspace_no_refetch_does_not_raise(tmp_path):
    """Regression: auto_fix_loop calls apply_commit_push_and_open_pr up to 3x in
    the SAME workspace/branch with no re-clone or `git fetch` between attempts
    (see auto_fix_loop.run_auto_fix_loop). The push target is a raw token-embedded
    URL, never a registered `origin` remote, so the local remote-tracking ref is
    never refreshed by these pushes. `--force-with-lease` (no explicit expected
    value) falls back to that stale tracking ref and rejects attempt 2/3 with
    "stale info" even though there is no real concurrent writer — SCRUM-85.

    Uses a real local bare repo (no mocked git) to faithfully reproduce git's
    lease-comparison behavior; only the GitHub PR-creation HTTP call is mocked.
    """
    bare_remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare_remote)], check=True)

    workspace = tmp_path / "workspace"
    subprocess.run(["git", "clone", "-q", str(bare_remote), str(workspace)], check=True)
    (workspace / "README.md").write_text("init\n")
    subprocess.run(["git", "-C", str(workspace), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(workspace), "-c", "user.email=t@t.test", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True,
    )
    # Push initial commit to `main` so the branch's base exists on the remote.
    subprocess.run(["git", "-C", str(workspace), "push", "-q", str(bare_remote), "HEAD:main"], check=True)

    respx.post(f"{GITHUB_API_BASE}/repos/acme/my-app/pulls").mock(
        return_value=httpx.Response(201, json=_make_pr_api_response())
    )

    # The production code always builds an https://oauth2:<token>@<host>/... push
    # URL (real network format). To exercise real git push/lease mechanics against
    # a local bare repo (no network), wrap subprocess.run: for the `git push` call
    # only, rewrite the bogus https URL arg to the local bare-repo path before
    # delegating to the real subprocess.run. Every other git call passes through
    # untouched.
    real_run = subprocess.run

    def _rewriting_run(args, *a, **kw):
        if isinstance(args, list) and len(args) >= 2 and args[0] == "git" and args[1] == "push":
            args = list(args)
            for i, arg in enumerate(args):
                if arg.startswith("https://oauth2:"):
                    args[i] = str(bare_remote)
        return real_run(args, *a, **kw)

    with patch("services.pr_creator.subprocess.run", side_effect=_rewriting_run):
        for attempt in range(1, 4):
            result = apply_commit_push_and_open_pr(
                workspace_path=str(workspace),
                github_repo=GITHUB_REPO,
                github_token="dummy-token",
                issue_key=ISSUE_KEY,
                file_changes=[FileChange(path=f"src/attempt_{attempt}.py", content=f"x = {attempt}\n")],
                branch_name="jarvis/qa-fix-SCRUM-85",
            )
            assert isinstance(result, PullRequest), f"attempt {attempt} failed to return a PullRequest"


# ---------------------------------------------------------------------------
# PRMERGE-01 tests — find_and_merge_pr (Phase 17 Plan 01)
# ---------------------------------------------------------------------------


from services.pr_creator import find_and_merge_pr, MergeResult  # noqa: E402

MERGE_TOKEN = "ghp_MERGE_TOKEN_SECRET"
MERGE_REPO = "owner/repo"
MERGE_ISSUE_KEY = "PROJ-1"
MERGE_PR_NUMBER = 42
MERGE_PR_URL = "https://github.com/owner/repo/pull/42"
MERGE_SHA = "abc123def456"

OPEN_PR_BY_BRANCH = {
    "number": MERGE_PR_NUMBER,
    "html_url": MERGE_PR_URL,
    "title": "feat: some unrelated title",
    "head": {"ref": f"jarvis/issue-{MERGE_ISSUE_KEY}"},
}

OPEN_PR_BY_TITLE = {
    "number": MERGE_PR_NUMBER,
    "html_url": MERGE_PR_URL,
    "title": f"{MERGE_ISSUE_KEY}: feat description",
    "head": {"ref": "unrelated-branch"},
}

MERGE_RESPONSE = {
    "sha": MERGE_SHA,
    "merged": True,
    "message": "Pull Request successfully merged",
}


@respx.mock
def test_find_and_merge_pr_by_branch():
    """GET /pulls?state=open → branch match → calls PUT /merge → returns MergeResult."""
    respx.get(f"{GITHUB_API_BASE}/repos/owner/repo/pulls").mock(
        return_value=httpx.Response(200, json=[OPEN_PR_BY_BRANCH])
    )
    respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/{MERGE_PR_NUMBER}/merge").mock(
        return_value=httpx.Response(200, json=MERGE_RESPONSE)
    )

    result = find_and_merge_pr(MERGE_REPO, MERGE_TOKEN, MERGE_ISSUE_KEY)

    assert isinstance(result, MergeResult)
    assert result.merged is True
    assert result.sha == MERGE_SHA
    assert result.pr_number == MERGE_PR_NUMBER
    assert result.pr_url == MERGE_PR_URL


@respx.mock
def test_find_and_merge_pr_by_title_fallback():
    """No branch match but title contains issue_key → title fallback match → merges OK."""
    respx.get(f"{GITHUB_API_BASE}/repos/owner/repo/pulls").mock(
        return_value=httpx.Response(200, json=[OPEN_PR_BY_TITLE])
    )
    respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/{MERGE_PR_NUMBER}/merge").mock(
        return_value=httpx.Response(200, json=MERGE_RESPONSE)
    )

    result = find_and_merge_pr(MERGE_REPO, MERGE_TOKEN, MERGE_ISSUE_KEY)

    assert isinstance(result, MergeResult)
    assert result.pr_number == MERGE_PR_NUMBER


@respx.mock
def test_find_and_merge_pr_returns_none_when_no_match():
    """GET /pulls returns [] → find_and_merge_pr returns None; PUT never called."""
    respx.get(f"{GITHUB_API_BASE}/repos/owner/repo/pulls").mock(
        return_value=httpx.Response(200, json=[])
    )
    merge_route = respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/{MERGE_PR_NUMBER}/merge").mock(
        return_value=httpx.Response(200, json=MERGE_RESPONSE)
    )

    result = find_and_merge_pr(MERGE_REPO, MERGE_TOKEN, MERGE_ISSUE_KEY)

    assert result is None
    assert not merge_route.called


@respx.mock
def test_find_and_merge_pr_raises_runtime_error_on_405(caplog):
    """PUT merge returns 405 → RuntimeError raised; github_token must not be in message."""
    respx.get(f"{GITHUB_API_BASE}/repos/owner/repo/pulls").mock(
        return_value=httpx.Response(200, json=[OPEN_PR_BY_BRANCH])
    )
    respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/{MERGE_PR_NUMBER}/merge").mock(
        return_value=httpx.Response(405, json={"message": "Not mergeable"})
    )

    with caplog.at_level(logging.WARNING, logger="services.pr_creator"):
        with pytest.raises(RuntimeError) as exc_info:
            find_and_merge_pr(MERGE_REPO, MERGE_TOKEN, MERGE_ISSUE_KEY)

    # T-17-01: token must never appear in exception message or log output
    assert MERGE_TOKEN not in str(exc_info.value)
    all_log_text = " ".join(record.getMessage() for record in caplog.records)
    assert MERGE_TOKEN not in all_log_text, "github_token leaked in log (T-17-01)"


def test_find_and_merge_pr_invalid_repo_raises_value_error():
    """Malformed github_repo slug → ValueError; httpx is never called."""
    with pytest.raises(ValueError, match="Invalid github_repo"):
        find_and_merge_pr("not-a-slug", MERGE_TOKEN, MERGE_ISSUE_KEY)


@respx.mock
def test_find_and_merge_pr_token_only_in_auth_header(caplog):
    """T-17-01: github_token only appears in Authorization header; never in URL or logs."""
    captured_requests = []

    def capture_get(request, route):
        captured_requests.append(("GET", request))
        return httpx.Response(200, json=[OPEN_PR_BY_BRANCH])

    def capture_put(request, route):
        captured_requests.append(("PUT", request))
        return httpx.Response(200, json=MERGE_RESPONSE)

    respx.get(f"{GITHUB_API_BASE}/repos/owner/repo/pulls").mock(side_effect=capture_get)
    respx.put(f"{GITHUB_API_BASE}/repos/owner/repo/pulls/{MERGE_PR_NUMBER}/merge").mock(
        side_effect=capture_put
    )

    with caplog.at_level(logging.INFO, logger="services.pr_creator"):
        find_and_merge_pr(MERGE_REPO, MERGE_TOKEN, MERGE_ISSUE_KEY)

    assert captured_requests, "No HTTP requests captured"
    for method, req in captured_requests:
        # Token must NOT appear in the URL
        assert MERGE_TOKEN not in str(req.url), f"Token in {method} URL — T-17-01 violation"
        # Token IS expected in Authorization header only
        auth_header = req.headers.get("authorization", "")
        assert MERGE_TOKEN in auth_header, f"Token missing from {method} Authorization header"

    # Token must not appear in any log output
    all_log_text = " ".join(record.getMessage() for record in caplog.records)
    assert MERGE_TOKEN not in all_log_text, "Token leaked in log output (T-17-01)"
