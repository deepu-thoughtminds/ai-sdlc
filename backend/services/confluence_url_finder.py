"""Pure utility to extract the most recent Confluence architecture page URL from Jira comments.

This module is intentionally dependency-free (only stdlib `re`) so it can be
unit-tested independently without any database, HTTP, or LLM dependencies.

Usage:
    from services.confluence_url_finder import find_latest_architecture_url

    url = find_latest_architecture_url(comments)  # list[dict] from hermes get_comments
    if url is None:
        # No architecture page found; post an informative Jira comment instead
        ...
"""
import re

# Matches Confluence wiki page URLs.
# Pattern: https?://<host>/wiki/spaces/<space>/pages/<numeric-id>
# Matches both atlassian.net cloud and self-hosted Confluence instances.
CONFLUENCE_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+/wiki/spaces/[^\s<>\"'/]+/pages/\d+"
)


def find_latest_architecture_url(comments: list[dict]) -> str | None:
    """Scan Jira comment history and return the most recent Confluence page URL.

    Jira returns comments in oldest-first order; we iterate newest-first so
    the most recent architecture URL is returned when multiple are present.

    The function is pure (no I/O, no side effects) — all input is the comment
    list, output is the first matched URL string or None.

    Args:
        comments: List of Jira comment dicts, as returned by hermes get_comments.
                  Each dict should have a "body" field containing the comment text.
                  Missing or non-string body values are skipped gracefully.

    Returns:
        The most recently posted Confluence architecture page URL, or None if
        no Confluence page URL is found in any comment.
    """
    # Iterate newest-first (Jira returns oldest-first, so reverse)
    for comment in reversed(comments):
        body = comment.get("body", "")
        if not isinstance(body, str):
            continue
        match = CONFLUENCE_URL_PATTERN.search(body)
        if match:
            return match.group(0)
    return None
