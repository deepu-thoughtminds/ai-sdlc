"""Pull request creation service — DEVPIPE-04.

Applies file changes to a cloned workspace, commits them on a new branch
named `jarvis/issue-{key}`, pushes to the remote, and opens a PR against
the `main` branch via the GitHub REST API.

Branch naming convention: `jarvis/issue-{key}` (e.g. `jarvis/issue-PROJ-42`)
— consistent with the `jarvis` agent branding used throughout the platform.

Security notes:
  - GitHub token is embedded in the authenticated push URL but NEVER logged.
  - subprocess.run calls NEVER use shell=True (no shell injection).
  - PR body is constructed from issue_key/pr_title only — no token values.

Threat mitigations:
  T-07-01: github_token never logged; only owner/repo/branch logged at INFO.
  T-07-02: subprocess.run uses list-form args, not shell=True.
  T-07-03: Error responses from GitHub API are logged without credential values.
  T-17-01: github_token never interpolated into f-strings, exception messages,
            or logger calls in find_and_merge_pr — mirrors T-07-01 convention.
"""

import logging
import os
import subprocess
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_HOST = os.environ.get("GITHUB_HOST", "github.com")

# Default base branch for all PRs (matches DEVPIPE-04 requirement)
DEFAULT_BASE_BRANCH = "main"


@dataclass
class PullRequest:
    """Result of a successfully created GitHub pull request.

    Fields:
        html_url:   The GitHub PR URL (e.g. "https://github.com/org/repo/pull/42").
        number:     The PR number.
        branch:     The head branch name (e.g. "jarvis/issue-PROJ-42").
    """

    html_url: str
    number: int
    branch: str


@dataclass
class MergeResult:
    """Result of a successfully merged GitHub pull request — PRMERGE-01.

    Fields:
        merged:     True if the PR was merged successfully.
        sha:        The merge commit SHA returned by the GitHub API.
        pr_number:  The PR number that was merged.
        pr_url:     The GitHub PR URL (html_url from the PR list).
    """

    merged: bool
    sha: str
    pr_number: int
    pr_url: str


def _run_git(args: list[str], cwd: str, github_token: str = "") -> subprocess.CompletedProcess:
    """Run a git command in the given directory.

    T-07-01: Replaces any occurrence of github_token in stderr before logging.
    T-07-02: Never uses shell=True.

    Args:
        args:         git CLI arguments (e.g. ["checkout", "-b", "branch-name"]).
        cwd:          Working directory (workspace_path of the cloned repo).
        github_token: Used only to scrub from error output — never passed as arg.

    Returns:
        subprocess.CompletedProcess result.

    Raises:
        RuntimeError: If the git command exits with non-zero status.
    """
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        # Never shell=True — T-07-02
    )

    if result.returncode != 0:
        # Scrub token from stderr AND from the args representation before logging (T-07-01).
        # args[1] for `git push` is the authenticated URL containing the token.
        safe_stderr = result.stderr
        safe_args_repr = " ".join(args[:2])
        if github_token:
            safe_stderr = safe_stderr.replace(github_token, "***")
            safe_args_repr = safe_args_repr.replace(github_token, "***")
        logger.warning(
            "git %s failed (exit=%d): %s",
            safe_args_repr,
            result.returncode,
            safe_stderr,
        )
        raise RuntimeError(
            f"git {safe_args_repr} failed with exit code {result.returncode}"
        )

    return result


def apply_commit_push_and_open_pr(
    workspace_path: str,
    github_repo: str,
    github_token: str,
    issue_key: str,
    file_changes: list,
    pr_title: str = "",
    pr_body: str = "",
    base_branch: str = DEFAULT_BASE_BRANCH,
) -> PullRequest:
    """Apply file changes to the cloned workspace, commit, push, and open a PR.

    DEVPIPE-04: Generated file changes are applied to the cloned workspace,
    committed on a new branch named `jarvis/issue-{key}`, pushed, and a PR
    is opened against `main` via the GitHub REST API.

    Steps:
      1. Configure git user in the workspace (required for commits).
      2. Create and checkout a new branch `jarvis/issue-{issue_key}`.
      3. Write each FileChange to disk (creating parent dirs as needed).
      4. Stage all changes with `git add -A`.
      5. Commit with message "feat: jarvis autonomous changes for {issue_key}".
      6. Push the branch to the remote (with token-embedded URL, never logged).
      7. POST to GitHub API to open a PR from the branch against `base_branch`.

    T-07-01: github_token is never logged. The push URL contains the token but
    is constructed only in-memory and passed as a subprocess arg (not shell cmd).
    T-07-02: All subprocess.run calls use list args, never shell=True.

    Args:
        workspace_path: Absolute path to the cloned repository workspace.
        github_repo:    Owner/repo slug (e.g. "acme/my-app"), plaintext decrypted.
        github_token:   GitHub personal access token, plaintext decrypted.
        issue_key:      Jira issue key (e.g. "PROJ-42").
        file_changes:   List of FileChange instances (from code_generator).
        pr_title:       PR title. Defaults to "feat: Jarvis changes for {issue_key}".
        pr_body:        PR body/description. Defaults to a link-back to the Jira ticket.
        base_branch:    Target branch for the PR. Defaults to "main".

    Returns:
        PullRequest dataclass with html_url, number, and branch.

    Raises:
        ValueError:  If github_repo cannot be parsed as owner/repo.
        RuntimeError: If any git command or the GitHub API call fails.
    """
    import pathlib

    if "/" not in github_repo:
        raise ValueError(f"Invalid github_repo slug: {github_repo!r}")

    parts = github_repo.strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid github_repo slug: {github_repo!r}")

    owner, repo = parts[0], parts[1]
    branch_name = f"jarvis/issue-{issue_key}"

    if not pr_title:
        pr_title = f"feat: Jarvis autonomous changes for {issue_key}"

    if not pr_body:
        pr_body = (
            f"Automated code changes generated by Jarvis for Jira ticket {issue_key}.\n\n"
            f"This PR was created autonomously by the Jarvis AI dev pipeline."
        )

    logger.info("Applying changes for %s on branch %s", issue_key, branch_name)

    # Step 1: Configure git user in workspace (needed to commit)
    # Pass github_token to all _run_git calls so the token is scrubbed from
    # any error output regardless of which command fails (T-07-01).
    _run_git(
        ["config", "user.email", "jarvis-bot@ai-sdlc.local"],
        cwd=workspace_path,
        github_token=github_token,
    )
    _run_git(
        ["config", "user.name", "Jarvis Bot"],
        cwd=workspace_path,
        github_token=github_token,
    )

    # Step 2: Create and checkout new branch
    _run_git(["checkout", "-b", branch_name], cwd=workspace_path, github_token=github_token)
    logger.info("Created branch %s in workspace %s", branch_name, workspace_path)

    if not file_changes:
        raise ValueError("file_changes must not be empty — nothing to commit")

    # Step 3: Write each FileChange to disk
    workspace_root = pathlib.Path(workspace_path).resolve()
    for change in file_changes:
        # Resolve to catch `..` traversal and absolute-path overrides (T-15-06)
        resolved = (workspace_root / change.path).resolve()
        if not str(resolved).startswith(str(workspace_root) + "/") and resolved != workspace_root:
            raise ValueError(
                f"FileChange path escapes workspace: '{change.path}' resolves to '{resolved}'"
            )
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(change.content, encoding="utf-8")
        logger.info("Applied change to: %s", change.path)

    # Step 4: Stage all changes
    _run_git(["add", "-A"], cwd=workspace_path, github_token=github_token)

    # Step 5: Commit
    commit_message = f"feat: jarvis autonomous changes for {issue_key}"
    _run_git(["commit", "-m", commit_message], cwd=workspace_path, github_token=github_token)
    logger.info("Committed changes for %s", issue_key)

    # Step 6: Push branch — token-embedded URL never logged (T-07-01)
    github_host = os.environ.get("GITHUB_HOST", GITHUB_HOST)
    # Use oauth2: scheme — x-access-token: triggers a spurious write-access
    # check on GitHub's git smart-HTTP backend for fine-grained PATs.
    push_url = f"https://oauth2:{github_token}@{github_host}/{owner}/{repo}.git"
    _run_git(
        ["push", push_url, branch_name],
        cwd=workspace_path,
        github_token=github_token,
    )
    logger.info("Pushed branch %s for %s/%s", branch_name, owner, repo)

    # Step 7: Open PR via GitHub REST API
    api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    pr_payload = {
        "title": pr_title,
        "head": branch_name,
        "base": base_branch,
        "body": pr_body,
    }

    try:
        resp = httpx.post(
            f"{api_base}/repos/{owner}/{repo}/pulls",
            headers=headers,
            json=pr_payload,
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Log response body without leaking the token (it's in headers, not body)
        logger.warning(
            "GitHub create PR failed for %s/%s: HTTP %s — %s",
            owner,
            repo,
            exc.response.status_code,
            exc.response.text[:500],
        )
        raise RuntimeError(
            f"GitHub PR creation failed for {owner}/{repo}: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        logger.warning("GitHub PR API error for %s/%s: %s", owner, repo, exc)
        raise RuntimeError(f"GitHub PR creation failed for {owner}/{repo}: {exc}") from exc

    pr_data = resp.json()
    pr_url = pr_data.get("html_url", "")
    pr_number = pr_data.get("number", 0)

    logger.info(
        "Opened PR #%d for %s/%s: %s", pr_number, owner, repo, pr_url
    )

    return PullRequest(html_url=pr_url, number=pr_number, branch=branch_name)


def find_and_merge_pr(
    github_repo: str,
    github_token: str,
    issue_key: str,
    base_branch: str = DEFAULT_BASE_BRANCH,
) -> "MergeResult | None":
    """Find the open PR for a Jira issue and merge it into main via the GitHub REST API.

    PRMERGE-01: Locates the open PR whose head branch is `jarvis/issue-{issue_key}`
    (preferred) or whose title contains `issue_key` (fallback), then merges it.

    Returns None if no matching open PR is found — never raises in the no-match case.

    Threat mitigations:
      T-17-01: github_token is placed ONLY in the `Authorization` header dict;
               never interpolated into f-strings, exception messages, or logger calls.

    Args:
        github_repo:  Owner/repo slug (e.g. "acme/my-app"), plaintext decrypted.
        github_token: GitHub personal access token, plaintext decrypted.
        issue_key:    Jira issue key (e.g. "PROJ-42").
        base_branch:  Target branch (default "main") — informational only for this
                      function; the PR's base branch is already set on GitHub.

    Returns:
        MergeResult(merged, sha, pr_number, pr_url) on successful merge, or None
        if no open PR matches the issue_key.

    Raises:
        ValueError:   If github_repo cannot be parsed as owner/repo.
        RuntimeError: If the GitHub API list-pulls or merge call fails.
    """
    if "/" not in github_repo:
        raise ValueError(f"Invalid github_repo slug: {github_repo!r}")

    parts = github_repo.strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid github_repo slug: {github_repo!r}")

    owner, repo = parts[0], parts[1]
    expected_branch = f"jarvis/issue-{issue_key}"

    # T-17-01: github_token only in Authorization header — never in URLs or log args.
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    # WR-03 fix: re-read GITHUB_API_BASE from the environment at call time
    # (matching apply_commit_push_and_open_pr) so test overrides via
    # os.environ take effect even after module import.
    api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)

    logger.info("Searching for open PR for %s in %s/%s", issue_key, owner, repo)

    # Step 1: List open PRs
    # WR-04 fix: request per_page=100 (GitHub API max) so the jarvis-created
    # PR is not missed when the repo has more than the default page size (30)
    # of open PRs.
    try:
        resp = httpx.get(
            f"{api_base}/repos/{owner}/{repo}/pulls",
            headers=headers,
            params={"state": "open", "per_page": 100},
            timeout=30.0,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "GitHub list PRs failed for %s/%s: HTTP %s — %s",
            owner,
            repo,
            exc.response.status_code,
            exc.response.text[:500],
        )
        raise RuntimeError(
            f"GitHub list PRs failed for {owner}/{repo}: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        logger.warning("GitHub list PRs API error for %s/%s: %s", owner, repo, exc)
        raise RuntimeError(f"GitHub list PRs failed for {owner}/{repo}: {exc}") from exc

    pull_list = resp.json()

    # Step 2: Match by branch name (preferred) then title (fallback)
    matched_pr = None
    for pr in pull_list:
        if pr.get("head", {}).get("ref") == expected_branch:
            matched_pr = pr
            break

    if matched_pr is None:
        for pr in pull_list:
            if issue_key in pr.get("title", ""):
                matched_pr = pr
                break

    if matched_pr is None:
        logger.info("No open PR found for %s in %s/%s", issue_key, owner, repo)
        return None

    pr_number = matched_pr["number"]
    pr_url = matched_pr.get("html_url", "")
    logger.info("Found open PR #%d for %s in %s/%s", pr_number, issue_key, owner, repo)

    # Step 3: Merge the PR
    merge_commit_title = f"Merge pull request #{pr_number}"
    try:
        merge_resp = httpx.put(
            f"{api_base}/repos/{owner}/{repo}/pulls/{pr_number}/merge",
            headers=headers,
            json={"commit_title": merge_commit_title},
            timeout=30.0,
        )
        merge_resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "GitHub merge PR #%d failed for %s/%s: HTTP %s — %s",
            pr_number,
            owner,
            repo,
            exc.response.status_code,
            exc.response.text[:500],
        )
        raise RuntimeError(
            f"GitHub merge PR #{pr_number} failed for {owner}/{repo}: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        logger.warning("GitHub merge API error for %s/%s PR #%d: %s", owner, repo, pr_number, exc)
        raise RuntimeError(
            f"GitHub merge PR #{pr_number} failed for {owner}/{repo}: {exc}"
        ) from exc

    merge_data = merge_resp.json()
    sha = merge_data.get("sha", "")
    merged = bool(merge_data.get("merged", False))

    logger.info("Merged PR #%d for %s in %s/%s — sha=%s", pr_number, issue_key, owner, repo, sha)

    return MergeResult(merged=merged, sha=sha, pr_number=pr_number, pr_url=pr_url)
