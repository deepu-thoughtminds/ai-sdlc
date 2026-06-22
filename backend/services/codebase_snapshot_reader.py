"""Standalone reader for the codebase snapshot stored at .hermes/codebase.md.

Implements SNAPSHOT-02 graceful degradation: every failure path returns None
rather than raising or surfacing an error to the caller.

Threat mitigations:
  T-19-04: github_token NEVER passed to any logger.*; only owner/repo/exc logged
  T-19-05: httpx timeout=15.0 bounds the request; timeout/connection errors are
           caught and converted to None
  T-19-06: 404 (file not yet committed) is treated as INFO, not WARNING —
           normal expected state for repos that haven't been scanned yet

Future callers:
  Phase 20 — describe_pipeline.py
  Phase 21 — architecture_pipeline.py
"""

import base64
import logging
import os

import httpx

from services.codebase_scan_service import GITHUB_API_BASE, _parse_owner_repo

logger = logging.getLogger(__name__)


async def get_codebase_snapshot(github_repo: str, github_token: str) -> str | None:
    """Fetch .hermes/codebase.md content from the GitHub Contents API.

    Returns the decoded markdown string when the file exists, or None when:
    - The file is absent (404) — normal state before first scan
    - The GitHub API errors (network timeout, 5xx, etc.)
    - The repo slug is invalid (no HTTP call is made)

    This function NEVER raises. It is the caller's responsibility to handle
    None as "no codebase context available". See SNAPSHOT-02 requirement.

    T-19-04: github_token never appears in any log message or exception string.
    """
    parsed = _parse_owner_repo(github_repo)
    if parsed is None:
        # _parse_owner_repo already logs a warning about the bad slug
        return None

    owner, repo = parsed
    api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)

    # T-19-04: token only ever placed in this Authorization header dict — never logged
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            resp = await client.get(
                f"{api_base}/repos/{owner}/{repo}/contents/.hermes/codebase.md"
            )

        if resp.status_code == 404:
            logger.info(
                "No codebase snapshot found for %s/%s — continuing without context",
                owner,
                repo,
            )
            return None

        resp.raise_for_status()

        content_b64 = resp.json().get("content")
        if not content_b64:
            return None
        return base64.b64decode(content_b64).decode("utf-8", errors="replace")

    except Exception as exc:
        # T-19-04: owner, repo, exc logged — never github_token
        logger.warning(
            "Codebase snapshot fetch failed for %s/%s: %s — continuing without context",
            owner,
            repo,
            exc,
        )
        return None
