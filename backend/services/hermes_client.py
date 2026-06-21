"""Async HTTP client for Hermes internal /jira/* endpoints.

Replaces direct JiraClient calls in backend services — each function
calls the hermes container's internal API which proxies through mcp-atlassian.

Threat mitigations:
- T-09-01: jira_token never logged; only issue_key/project_key logged at INFO.
- T-09-03: timeout=15.0 on all requests; post_sprint_backlog returns [] on any error.
"""
import logging
import os

import httpx

HERMES_BASE_URL: str = os.getenv("HERMES_BASE_URL", "http://hermes:8001")
logger = logging.getLogger(__name__)


async def post_comment(
    jira_url: str,
    jira_email: str,
    jira_token: str,
    issue_key: str,
    body: str,
) -> dict:
    """Post a comment to a Jira issue via hermes. Returns the response dict."""
    logger.info("Posting comment to issue %s", issue_key)
    payload = {
        "jira_url": jira_url,
        "jira_email": jira_email,
        "jira_token": jira_token,
        "issue_key": issue_key,
        "body": body,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{HERMES_BASE_URL}/jira/comment", json=payload)
    resp.raise_for_status()
    return resp.json()


async def put_description(
    jira_url: str,
    jira_email: str,
    jira_token: str,
    issue_key: str,
    description: str,
) -> dict:
    """Update the description of a Jira issue via hermes. Returns {} on success."""
    logger.info("Updating description for issue %s", issue_key)
    payload = {
        "jira_url": jira_url,
        "jira_email": jira_email,
        "jira_token": jira_token,
        "issue_key": issue_key,
        "description": description,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.put(f"{HERMES_BASE_URL}/jira/description", json=payload)
    resp.raise_for_status()
    if resp.status_code == 204 or not resp.content:
        return {}
    return resp.json()


async def post_sprint_backlog(
    jira_url: str,
    jira_email: str,
    jira_token: str,
    project_key: str,
) -> list[dict]:
    """Fetch open sprint issues for a project via hermes.

    Returns [] on any error — mirrors JiraClient.get_sprint_backlog fallback.
    """
    try:
        payload = {
            "jira_url": jira_url,
            "jira_email": jira_email,
            "jira_token": jira_token,
            "project_key": project_key,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{HERMES_BASE_URL}/jira/sprint-backlog", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(
            "post_sprint_backlog failed for project %s: %s — returning []",
            project_key,
            exc,
        )
        return []


async def post_assign(
    jira_url: str,
    jira_email: str,
    jira_token: str,
    issue_key: str,
    display_name: str,
) -> str:
    """Assign a Jira issue to a user via hermes. Returns the accountId string.

    Raises httpx.HTTPStatusError on any non-2xx (including user-not-found 500).
    Callers must catch to handle the not-found case.
    """
    logger.info("Assigning issue %s to '%s'", issue_key, display_name)
    payload = {
        "jira_url": jira_url,
        "jira_email": jira_email,
        "jira_token": jira_token,
        "issue_key": issue_key,
        "display_name": display_name,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{HERMES_BASE_URL}/jira/assign", json=payload)
    resp.raise_for_status()
    return str(resp.json()["account_id"])


# ---------------------------------------------------------------------------
# Confluence functions
# ---------------------------------------------------------------------------


async def create_confluence_page(
    confluence_url: str,
    confluence_email: str,
    confluence_token: str,
    space_key: str,
    title: str,
    body_html: str,
) -> dict:
    """Create a new Confluence page via hermes. Returns the response dict (includes "id").

    T-04-05: confluence_token is never logged; only space_key and title are logged.
    """
    logger.info("Creating Confluence page in space %s: %s", space_key, title)
    payload = {
        "confluence_url": confluence_url,
        "confluence_email": confluence_email,
        "confluence_token": confluence_token,
        "space_key": space_key,
        "title": title,
        "body_html": body_html,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{HERMES_BASE_URL}/confluence/page", json=payload)
    resp.raise_for_status()
    return resp.json()


async def update_confluence_page(
    confluence_url: str,
    confluence_email: str,
    confluence_token: str,
    page_id: str,
    title: str,
    body_html: str,
    version: int,
) -> dict:
    """Update an existing Confluence page via hermes. Returns the response dict.

    T-04-05: confluence_token is never logged; only page_id and title are logged.
    """
    logger.info("Updating Confluence page %s: %s", page_id, title)
    payload = {
        "confluence_url": confluence_url,
        "confluence_email": confluence_email,
        "confluence_token": confluence_token,
        "title": title,
        "body_html": body_html,
        "version": version,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.put(f"{HERMES_BASE_URL}/confluence/page/{page_id}", json=payload)
    resp.raise_for_status()
    return resp.json()


async def find_confluence_page(
    confluence_url: str,
    confluence_email: str,
    confluence_token: str,
    space_key: str,
    title: str,
) -> dict | None:
    """Search for a Confluence page by space and title via hermes.

    Returns the page dict if found, or None if not found.
    Translates the hermes-layer empty-dict convention ({}) back to None.

    T-04-05: confluence_token is never logged; only space_key and title are logged.
    """
    logger.info("Searching for Confluence page in space %s: %s", space_key, title)
    params = {
        "confluence_url": confluence_url,
        "confluence_email": confluence_email,
        "confluence_token": confluence_token,
        "space_key": space_key,
        "title": title,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{HERMES_BASE_URL}/confluence/search", params=params)
    resp.raise_for_status()
    data = resp.json()
    # Hermes returns {} when not found — translate back to None
    if data == {}:
        return None
    return data


# ---------------------------------------------------------------------------
# Phase 16 Plan 01: Comment and Confluence page content fetch functions
# ---------------------------------------------------------------------------


async def get_comments(
    jira_url: str,
    jira_email: str,
    jira_token: str,
    issue_key: str,
) -> list[dict]:
    """Fetch comment history for a Jira issue via hermes POST /jira/comments.

    Returns [] on any error — DEVPIPE-01 requires the pipeline to not crash
    if comment history is unavailable. The caller should post an informative
    Jira comment if no architecture URL is found after degradation.

    T-09-01: jira_token is never logged; only issue_key is logged at INFO.
    """
    try:
        logger.info("Fetching comments for issue %s", issue_key)
        payload = {
            "jira_url": jira_url,
            "jira_email": jira_email,
            "jira_token": jira_token,
            "issue_key": issue_key,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{HERMES_BASE_URL}/jira/comments", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(
            "get_comments failed for issue %s: %s — returning []",
            issue_key,
            exc,
        )
        return []


async def get_confluence_page_content(
    confluence_url: str,
    confluence_email: str,
    confluence_token: str,
    page_id: str,
) -> str:
    """Fetch the body content of a Confluence page by page ID via hermes.

    Returns "" on any error — degrades gracefully so the dev pipeline can
    proceed with an empty architecture context rather than crashing.

    T-04-05: confluence_token is never logged; only page_id is logged at INFO.
    """
    try:
        logger.info("Fetching Confluence page content for page %s", page_id)
        params = {
            "confluence_url": confluence_url,
            "confluence_email": confluence_email,
            "confluence_token": confluence_token,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{HERMES_BASE_URL}/confluence/page/{page_id}", params=params
            )
        resp.raise_for_status()
        data = resp.json()
        # Hermes wraps body in {"body": "<content string>"}
        return data.get("body", "") if isinstance(data, dict) else ""
    except Exception as exc:
        logger.warning(
            "get_confluence_page_content failed for page %s: %s — returning ''",
            page_id,
            exc,
        )
        return ""
