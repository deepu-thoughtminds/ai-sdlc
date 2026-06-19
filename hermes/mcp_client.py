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
