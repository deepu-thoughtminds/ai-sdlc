"""GitHub codebase summarizer for context-enriched description generation.

Fetches the repository tree and key Python module docstrings from the GitHub
API to build a StructuredCodebaseSummary used as context in the describe
pipeline prompt.

GITHUB_API_BASE env var defaults to "https://api.github.com". Override in
tests or staging environments.

Threat mitigations:
  T-03-03: Parse only owner/repo from stored github_url (from DB, already
           validated on onboard); reject malformed URLs with empty
           StructuredCodebaseSummary — never build URLs from arbitrary input.
"""

import base64
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")


@dataclass
class StructuredCodebaseSummary:
    """Structured summary of a GitHub repository's codebase.

    Fields:
        directory_tree: Newline-joined list of all repo file paths from the
                        GitHub tree API (up to the API limit).
        key_files:      List of .py file paths (up to 20) for deeper inspection.
        module_docs:    Mapping of file path → first docstring or first 200 chars
                        of the file content (best-effort; skipped on error).
    """

    directory_tree: str = ""
    key_files: list[str] = field(default_factory=list)
    module_docs: dict[str, str] = field(default_factory=dict)


def _parse_owner_repo(github_url: str) -> tuple[str, str] | None:
    """Parse owner and repo name from a GitHub URL.

    Handles formats:
      - https://github.com/owner/repo
      - https://github.com/owner/repo.git
      - https://github.com/owner/repo/

    T-03-03: reject malformed URLs by returning None.

    Args:
        github_url: The GitHub repository URL.

    Returns:
        (owner, repo) tuple or None if URL is malformed.
    """
    if not github_url:
        return None
    # Match https://github.com/{owner}/{repo}
    match = re.match(r"https?://github\.com/([^/]+)/([^/\s]+?)(?:\.git)?/?$", github_url.strip())
    if not match:
        logger.warning("Cannot parse owner/repo from github_url: %s", github_url)
        return None
    owner = match.group(1)
    repo = match.group(2)
    if not owner or not repo:
        return None
    return owner, repo


def _extract_docstring(content: str) -> str:
    """Extract the first triple-quoted docstring or return the first 200 chars.

    Args:
        content: Raw Python file content as a string.

    Returns:
        Docstring text (without quotes) or first 200 chars of content.
    """
    # Try to find the first triple-quoted string (single or double quotes)
    match = re.search(r'"""(.*?)"""', content, re.DOTALL)
    if match:
        return match.group(1).strip()
    match = re.search(r"'''(.*?)'''", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    # Fallback: return first 200 chars
    return content[:200].strip()


def get_codebase_summary(github_url: str, github_token: str) -> StructuredCodebaseSummary:
    """Fetch and summarize a GitHub repository's codebase structure.

    Steps:
    1. Parse owner/repo from github_url (reject malformed URLs).
    2. GET /repos/{owner}/{repo}/git/trees/HEAD?recursive=1 → file tree.
    3. Build directory_tree from all file paths.
    4. Filter to .py files (up to 20) → key_files.
    5. For each key_file: GET /repos/{owner}/{repo}/contents/{path}
       → decode base64 content → extract docstring → module_docs.

    On any GitHub API error: log warning and return empty StructuredCodebaseSummary.
    On content fetch error for a single file: log and skip (best-effort).

    T-03-03: github_url parsed via strict regex; no URL from user input.

    Args:
        github_url: The GitHub repository URL (from DB, validated on onboard).
        github_token: Decrypted GitHub personal access token (plaintext).

    Returns:
        StructuredCodebaseSummary with directory_tree, key_files, and module_docs.
    """
    # T-03-03: parse and validate URL
    parsed = _parse_owner_repo(github_url)
    if parsed is None:
        logger.warning("Invalid github_url — returning empty summary: %s", github_url)
        return StructuredCodebaseSummary()

    owner, repo = parsed
    api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        # Step 2: Fetch the recursive tree
        resp = httpx.get(
            f"{api_base}/repos/{owner}/{repo}/git/trees/HEAD",
            headers=headers,
            params={"recursive": "1"},
            timeout=20.0,
        )
        resp.raise_for_status()
        tree_data = resp.json()
    except Exception as exc:
        logger.warning(
            "GitHub tree fetch failed for %s/%s: %s — returning empty summary",
            owner,
            repo,
            exc,
        )
        return StructuredCodebaseSummary()

    # Step 3: Build directory_tree
    blobs = [item["path"] for item in tree_data.get("tree", []) if item.get("type") == "blob"]
    directory_tree = "\n".join(blobs)

    # Step 4: Filter to .py files (max 20)
    py_files = [p for p in blobs if p.endswith(".py")][:20]

    # Step 5: Fetch and extract docstrings for each .py file
    module_docs: dict[str, str] = {}
    for path in py_files:
        try:
            content_resp = httpx.get(
                f"{api_base}/repos/{owner}/{repo}/contents/{path}",
                headers=headers,
                timeout=10.0,
            )
            content_resp.raise_for_status()
            file_data = content_resp.json()
            # GitHub returns base64-encoded content
            raw_bytes = base64.b64decode(file_data.get("content", ""))
            raw_text = raw_bytes.decode("utf-8", errors="replace")
            module_docs[path] = _extract_docstring(raw_text)
        except Exception as exc:
            logger.warning("Skipping content fetch for %s: %s", path, exc)
            continue

    return StructuredCodebaseSummary(
        directory_tree=directory_tree,
        key_files=py_files,
        module_docs=module_docs,
    )
