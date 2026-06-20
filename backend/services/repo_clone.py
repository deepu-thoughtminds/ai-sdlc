"""GitHub repository cloning service — DEVPIPE-02.

Clones a GitHub repository into a temporary workspace directory using
subprocess.run with the git CLI (no GitPython dependency required).

The authenticated clone URL is constructed with an x-access-token embed:
  https://x-access-token:{github_token}@github.com/{owner}/{repo}.git

Security notes:
  - The token-embedded URL is NEVER logged — only owner/repo is logged.
  - subprocess.run calls never use shell=True (avoids shell injection).
  - The caller is responsible for cleaning up the workspace directory
    (tempfile.mkdtemp returns a path that persists until explicit removal).

Threat mitigations:
  T-05-01: github_token never appears in any log output; only owner/repo logged.
  T-05-02: subprocess.run uses list form, not shell=True — no shell injection possible.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GITHUB_HOST = os.environ.get("GITHUB_HOST", "github.com")


@dataclass
class ClonedRepo:
    """Result of a successful repository clone operation.

    Fields:
        workspace_path: Absolute path to the temporary directory containing
                        the cloned repository files. Caller must remove this
                        directory when done (e.g. shutil.rmtree).
        owner:          Parsed repository owner (e.g. "acme").
        repo:           Parsed repository name (e.g. "my-app").
    """

    workspace_path: str
    owner: str
    repo: str


def _parse_github_repo(github_repo: str) -> tuple[str, str] | None:
    """Parse owner and repo name from an owner/repo slug.

    Accepts the format "owner/repo" (e.g. "acme/my-app").
    Rejects empty strings, slugs without exactly one slash, or empty segments.

    Args:
        github_repo: An owner/repo slug (e.g. "acme/my-app").

    Returns:
        (owner, repo) tuple or None if the slug is malformed.
    """
    if not github_repo or "/" not in github_repo:
        logger.warning("Cannot parse owner/repo from github_repo slug: %r", github_repo)
        return None

    parts = github_repo.strip().split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        logger.warning("Malformed owner/repo slug: %r", github_repo)
        return None

    owner, repo = parts[0].strip(), parts[1].strip()
    if not owner or not repo:
        return None

    return owner, repo


def clone_repository(github_repo: str, github_token: str) -> ClonedRepo:
    """Clone a GitHub repository into a temporary workspace directory.

    DEVPIPE-02: Given a Project's decrypted github_token and github_repo slug,
    the agent clones the repo into a temporary workspace directory.

    T-05-01: The authenticated clone URL (which embeds the token) is NEVER
    logged — only owner/repo identifiers appear in log output.
    T-05-02: subprocess.run uses list-form args, not shell=True.

    Args:
        github_repo: Owner/repo slug (e.g. "acme/my-app"). Must be decrypted
                     before passing — this function receives plaintext.
        github_token: GitHub personal access token (plaintext, decrypted by
                      the caller via services.crypto.decrypt_credential).

    Returns:
        ClonedRepo dataclass with workspace_path, owner, and repo.

    Raises:
        ValueError: If github_repo is malformed and cannot be parsed.
        RuntimeError: If the git clone subprocess fails (non-zero exit code).
    """
    parsed = _parse_github_repo(github_repo)
    if parsed is None:
        raise ValueError(f"Invalid github_repo slug: {github_repo!r}")

    owner, repo = parsed
    github_host = os.environ.get("GITHUB_HOST", GITHUB_HOST)

    # Build authenticated URL — NEVER logged (T-05-01)
    clone_url = f"https://x-access-token:{github_token}@{github_host}/{owner}/{repo}.git"

    # Create temporary workspace directory
    workspace_path = tempfile.mkdtemp(prefix=f"jarvis-{owner}-{repo}-")

    logger.info("Cloning %s/%s into temporary workspace", owner, repo)

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, workspace_path],
            capture_output=True,
            text=True,
            timeout=120,
            # Never shell=True — T-05-02
        )

        if result.returncode != 0:
            # Log only the stderr without the URL (which contains the token)
            # Replace any occurrence of the token in stderr before logging
            safe_stderr = result.stderr.replace(github_token, "***") if github_token else result.stderr
            logger.warning(
                "git clone failed for %s/%s (exit=%d): %s",
                owner,
                repo,
                result.returncode,
                safe_stderr,
            )
            # Clean up the workspace on failure
            try:
                shutil.rmtree(workspace_path, ignore_errors=True)
            except Exception:
                pass
            raise RuntimeError(
                f"git clone failed for {owner}/{repo} with exit code {result.returncode}"
            )

    except subprocess.TimeoutExpired:
        logger.warning("git clone timed out for %s/%s — removing workspace", owner, repo)
        try:
            shutil.rmtree(workspace_path, ignore_errors=True)
        except Exception:
            pass
        raise RuntimeError(f"git clone timed out for {owner}/{repo}")

    except RuntimeError:
        raise

    except Exception as exc:
        logger.warning("git clone subprocess error for %s/%s: %s", owner, repo, exc)
        try:
            shutil.rmtree(workspace_path, ignore_errors=True)
        except Exception:
            pass
        raise RuntimeError(f"git clone failed for {owner}/{repo}: {exc}") from exc

    logger.info("Cloned %s/%s to %s", owner, repo, workspace_path)
    return ClonedRepo(workspace_path=workspace_path, owner=owner, repo=repo)
