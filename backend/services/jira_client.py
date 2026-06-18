"""Jira REST API client for interacting with Jira Cloud.

Wraps the Jira REST API v3 and Agile API v1 endpoints required by the
description elaboration pipeline.

Authentication:
  Uses HTTP Basic auth: base64(email:token) per Jira Cloud documentation.
  The email is read from the JIRA_ACCOUNT_EMAIL env var if not passed directly.
  Token is the decrypted Jira API token from the project's encrypted store.

Threat mitigations:
  T-03-01: Authorization header is built from decrypted token at runtime.
           Token value is never written to logs — only issue_key is logged.
  T-03-04: base64(email:token) is standard Jira Cloud Basic auth.
           Token decrypted via Fernet upstream; email from env var.
  T-03-06: httpx timeout=15.0s; maxResults=50 cap on sprint issues;
           all Jira errors caught in get_sprint_backlog and return [].
"""

import base64
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class JiraClient:
    """Synchronous Jira REST API client using httpx.

    All public methods are synchronous (httpx.Client) for compatibility
    with FastAPI dependency injection without requiring async overhead at
    the service layer.

    Args:
        jira_url: Base URL of the Jira instance (e.g. "https://org.atlassian.net").
        token: Decrypted Jira API token (plaintext).
        email: Jira account email address. Used for Basic auth header.
               Defaults to empty string if not provided (some token-only setups).
    """

    def __init__(self, jira_url: str, token: str, email: str = "") -> None:
        self.base_url = jira_url.rstrip("/")
        # Build Basic auth header: base64(email:token)
        # T-03-04: standard Jira Cloud auth; token never logged
        raw = f"{email}:{token}".encode()
        self._auth_header = "Basic " + base64.b64encode(raw).decode()
        self._client = httpx.Client(timeout=15.0)

    def _headers(self) -> dict[str, str]:
        """Return standard Jira API request headers including auth."""
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def get_sprint_backlog(self, project_key: str) -> list[dict[str, Any]]:
        """Fetch issues from the active sprint for the given project.

        Steps:
        1. GET /rest/agile/1.0/board?projectKeyOrId={project_key} — find board id
        2. GET /rest/agile/1.0/board/{board_id}/sprint?state=active — find active sprint id
        3. GET /rest/agile/1.0/sprint/{sprint_id}/issue?maxResults=50 — get issues

        Returns a list of {"key": str, "summary": str, "issue_type": str} dicts.
        On any error or 404 at any step: logs a warning and returns [].

        Threat T-03-06: timeout=15.0s; maxResults=50; all errors return [].
        """
        try:
            # Step 1: find board for project
            resp = self._client.get(
                f"{self.base_url}/rest/agile/1.0/board",
                headers=self._headers(),
                params={"projectKeyOrId": project_key},
            )
            resp.raise_for_status()
            boards = resp.json().get("values", [])
            if not boards:
                logger.warning("No board found for project %s", project_key)
                return []
            board_id = boards[0]["id"]

            # Step 2: find active sprint
            resp = self._client.get(
                f"{self.base_url}/rest/agile/1.0/board/{board_id}/sprint",
                headers=self._headers(),
                params={"state": "active"},
            )
            resp.raise_for_status()
            sprints = resp.json().get("values", [])
            if not sprints:
                logger.warning("No active sprint for board %d", board_id)
                return []
            sprint_id = sprints[0]["id"]

            # Step 3: fetch issues in sprint
            resp = self._client.get(
                f"{self.base_url}/rest/agile/1.0/sprint/{sprint_id}/issue",
                headers=self._headers(),
                params={"maxResults": 50},
            )
            resp.raise_for_status()
            issues = resp.json().get("issues", [])

            return [
                {
                    "key": issue["key"],
                    "summary": issue["fields"].get("summary", ""),
                    "issue_type": issue["fields"].get("issuetype", {}).get("name", ""),
                }
                for issue in issues
            ]

        except Exception as exc:
            logger.warning(
                "get_sprint_backlog failed for project %s: %s — returning []",
                project_key,
                exc,
            )
            return []

    def get_issue(self, issue_key: str) -> dict[str, Any]:
        """Fetch a single Jira issue by key.

        GET /rest/api/3/issue/{issue_key}

        Args:
            issue_key: Jira issue key (e.g. "PROJ-123").

        Returns:
            Full response dict from the Jira API.

        Raises:
            httpx.HTTPStatusError: on non-2xx response.
        """
        # T-03-01: only issue_key is logged, never the token
        logger.info("Fetching issue %s", issue_key)
        resp = self._client.get(
            f"{self.base_url}/rest/api/3/issue/{issue_key}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def add_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        """Post a comment to a Jira issue using Atlassian Document Format (ADF).

        POST /rest/api/3/issue/{issue_key}/comment

        Args:
            issue_key: The Jira issue key.
            body: Plain text content for the comment.

        Returns:
            Response dict from the Jira API (the created comment).
        """
        logger.info("Adding comment to issue %s", issue_key)
        adf_body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": body}],
                    }
                ],
            }
        }
        resp = self._client.post(
            f"{self.base_url}/rest/api/3/issue/{issue_key}/comment",
            headers=self._headers(),
            json=adf_body,
        )
        resp.raise_for_status()
        return resp.json()

    def update_description(self, issue_key: str, description: str) -> dict[str, Any]:
        """Update the description of a Jira issue using ADF format.

        PUT /rest/api/3/issue/{issue_key}

        Args:
            issue_key: The Jira issue key.
            description: Plain text description to set.

        Returns:
            {} on 204 (Jira returns no body); response dict on 200.
        """
        logger.info("Updating description for issue %s", issue_key)
        payload = {
            "fields": {
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": description}],
                        }
                    ],
                }
            }
        }
        resp = self._client.put(
            f"{self.base_url}/rest/api/3/issue/{issue_key}",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        # Jira returns 204 No Content on successful PUT
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def lookup_user(self, display_name: str) -> str | None:
        """Look up a Jira user by display name and return their accountId.

        GET /rest/api/3/user/search?query={display_name}&maxResults=5

        Args:
            display_name: The user's display name to search for.

        Returns:
            The accountId of the first matching user, or None if no match.
        """
        logger.info("Looking up Jira user: %s", display_name)
        resp = self._client.get(
            f"{self.base_url}/rest/api/3/user/search",
            headers=self._headers(),
            params={"query": display_name, "maxResults": 5},
        )
        resp.raise_for_status()
        users = resp.json()
        if not users:
            return None
        return users[0].get("accountId")

    def assign_issue(self, issue_key: str, account_id: str) -> dict[str, Any]:
        """Assign a Jira issue to a user by their accountId.

        PUT /rest/api/3/issue/{issue_key}/assignee

        Args:
            issue_key: The Jira issue key.
            account_id: The Jira accountId of the assignee.

        Returns:
            {} on 204; response dict otherwise.
        """
        logger.info("Assigning issue %s to accountId %s", issue_key, account_id)
        resp = self._client.put(
            f"{self.base_url}/rest/api/3/issue/{issue_key}/assignee",
            headers=self._headers(),
            json={"accountId": account_id},
        )
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()
