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
