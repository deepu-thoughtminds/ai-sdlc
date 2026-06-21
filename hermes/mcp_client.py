"""Async MCP client for the Hermes agent, connecting to mcp-atlassian over HTTP/SSE."""
import base64
import dataclasses
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_ATLASSIAN_URL: str = os.getenv("MCP_ATLASSIAN_URL", "http://mcp-atlassian:9000/mcp")


@dataclasses.dataclass
class JiraCredentials:
    """Per-request Jira credentials for mcp-atlassian tool calls."""
    jira_url: str
    jira_email: str
    jira_token: str


@dataclasses.dataclass
class ConfluenceCredentials:
    """Per-request Confluence credentials for mcp-atlassian tool calls."""
    confluence_url: str
    confluence_email: str
    confluence_token: str


class HermesMCPClient:
    """Typed async wrapper over the MCP SDK for mcp-atlassian Jira operations.

    Each method opens a fresh HTTP connection per call — stateless, per-request design.
    Credentials are passed as HTTP headers (Authorization + x-atlassian-jira-url),
    which is what mcp-atlassian expects for per-request (multi-user) auth mode.
    """

    def __init__(self, mcp_url: str = MCP_ATLASSIAN_URL) -> None:
        self._mcp_url = mcp_url

    def _cred_headers(self, credentials: JiraCredentials) -> dict[str, str]:
        """Build HTTP headers for mcp-atlassian per-request authentication."""
        token = base64.b64encode(
            f"{credentials.jira_email}:{credentials.jira_token}".encode()
        ).decode()
        return {
            "Authorization": f"Basic {token}",
            "x-atlassian-jira-url": credentials.jira_url,
        }

    def _confluence_cred_headers(self, credentials: ConfluenceCredentials) -> dict[str, str]:
        """Build HTTP headers for mcp-atlassian Confluence per-request authentication.

        Uses x-atlassian-confluence-url (distinct from x-atlassian-jira-url — T-Q01-01)
        so mcp-atlassian does not conflate Jira and Confluence credential sets.
        """
        token = base64.b64encode(
            f"{credentials.confluence_email}:{credentials.confluence_token}".encode()
        ).decode()
        return {
            "Authorization": f"Basic {token}",
            "x-atlassian-confluence-url": credentials.confluence_url,
        }

    async def add_comment(
        self, issue_key: str, body: str, credentials: JiraCredentials
    ) -> str:
        """Add a comment to a Jira issue. Returns the created comment ID."""
        args = {"issue_key": issue_key, "body": body}
        async with streamablehttp_client(self._mcp_url, headers=self._cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("jira_add_comment", args)
        parsed = json.loads(result.content[0].text)
        return str(parsed["id"])

    async def update_description(
        self, issue_key: str, description: str, credentials: JiraCredentials
    ) -> None:
        """Update the description field of a Jira issue."""
        args = {
            "issue_key": issue_key,
            "fields": json.dumps({"description": description}),
        }
        async with streamablehttp_client(self._mcp_url, headers=self._cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("jira_update_issue", args)

    async def get_sprint_issues(
        self, project_key: str, credentials: JiraCredentials
    ) -> list[dict]:
        """Return open sprint issues for a project as [{key, summary, issue_type}]."""
        args = {
            "jql": f"project={project_key} AND sprint in openSprints()",
            "fields": "summary,issuetype",
        }
        async with streamablehttp_client(self._mcp_url, headers=self._cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("jira_search", args)
        parsed = json.loads(result.content[0].text)
        # Handle both {"issues": [...]} and flat list shapes
        issues = parsed.get("issues", parsed) if isinstance(parsed, dict) else parsed
        return [
            {
                "key": issue["key"],
                "summary": issue["fields"]["summary"],
                "issue_type": issue["fields"]["issuetype"]["name"],
            }
            for issue in issues
        ]

    async def lookup_user(
        self, display_name: str, credentials: JiraCredentials
    ) -> str:
        """Search for a Jira user by display name. Returns the accountId."""
        args = {"user_identifier": display_name}
        async with streamablehttp_client(self._mcp_url, headers=self._cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("jira_get_user_profile", args)
        parsed = json.loads(result.content[0].text)
        return str(parsed["user"]["accountId"])

    async def assign_issue(
        self, issue_key: str, account_id: str, credentials: JiraCredentials
    ) -> None:
        """Assign a Jira issue to a user by accountId."""
        args = {
            "issue_key": issue_key,
            "fields": json.dumps({"assignee": account_id}),
        }
        async with streamablehttp_client(self._mcp_url, headers=self._cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("jira_update_issue", args)

    # ---------------------------------------------------------------------------
    # Confluence MCP methods
    # ---------------------------------------------------------------------------

    async def create_confluence_page(
        self, space_key: str, title: str, body_html: str, credentials: ConfluenceCredentials
    ) -> dict:
        """Create a new Confluence page via MCP tool confluence_create_page.

        Opens a fresh per-request connection — stateless, no stored session.
        content_format="storage" is required because body_html is Confluence storage
        format HTML, not the tool's default markdown.

        Args:
            space_key: Confluence space key (e.g. "PROJ").
            title: Page title.
            body_html: HTML content for the page body (storage format).
            credentials: Per-request Confluence credentials.

        Returns:
            Parsed dict from MCP tool result (must include "id").
        """
        args = {
            "space_key": space_key,
            "title": title,
            "content": body_html,
            "content_format": "storage",
        }
        async with streamablehttp_client(self._mcp_url, headers=self._confluence_cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("confluence_create_page", args)
        parsed = json.loads(result.content[0].text)
        # Tool returns {"message": "...", "page": {"id": ..., ...}}; normalise to {"id": ...}
        return parsed.get("page", parsed)

    async def find_confluence_page(
        self, space_key: str, title: str, credentials: ConfluenceCredentials
    ) -> dict | None:
        """Search for a Confluence page by space and title via MCP tool confluence_search.

        Uses CQL-style query with limit=1 to bound the result set (T-12-04).
        Returns a normalised dict with shape {"id": str} if found, else None.
        The version field is not included because confluence_update_page auto-manages versions.
        """
        args = {
            "query": f'space = "{space_key}" AND title = "{title}"',
            "limit": 1,
        }
        async with streamablehttp_client(self._mcp_url, headers=self._confluence_cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("confluence_search", args)
        parsed = json.loads(result.content[0].text)
        if isinstance(parsed, list) and parsed:
            hit = parsed[0]
        elif isinstance(parsed, dict) and parsed.get("id"):
            hit = parsed
        else:
            return None
        page_id = hit.get("id", "")
        return {"id": page_id} if page_id else None

    async def update_confluence_page(
        self, page_id: str, title: str, body_html: str, version: int, credentials: ConfluenceCredentials
    ) -> dict:
        """Update an existing Confluence page via MCP tool confluence_update_page.

        Opens a fresh per-request connection — stateless, no stored session.
        The tool auto-manages the version number; `version` is accepted for API
        compatibility with callers but is NOT forwarded to the MCP tool.
        content_format="storage" is required because body_html is Confluence storage
        format HTML, not the tool's default markdown.

        Args:
            page_id: Confluence page id to update.
            title: Page title.
            body_html: New HTML content for the page body (storage format).
            version: Accepted for API compatibility; not forwarded (tool auto-manages).
            credentials: Per-request Confluence credentials.

        Returns:
            Parsed dict from MCP tool result.
        """
        args = {
            "page_id": page_id,
            "title": title,
            "content": body_html,
            "content_format": "storage",
        }
        async with streamablehttp_client(self._mcp_url, headers=self._confluence_cred_headers(credentials)) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("confluence_update_page", args)
        return json.loads(result.content[0].text)
