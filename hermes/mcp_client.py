"""Async MCP client for the Hermes agent, connecting to mcp-atlassian over HTTP/SSE."""
import dataclasses
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_ATLASSIAN_URL: str = os.getenv("MCP_ATLASSIAN_URL", "http://mcp-atlassian:9000/sse")


@dataclasses.dataclass
class JiraCredentials:
    """Per-request Jira credentials for mcp-atlassian tool calls."""
    jira_url: str
    jira_email: str
    jira_token: str


class HermesMCPClient:
    """Typed async wrapper over the MCP SDK for mcp-atlassian Jira operations.

    Each method opens a fresh HTTP/SSE connection per call — stateless, per-request design.
    Credentials are passed as tool arguments (never stored on the instance).
    """

    def __init__(self, mcp_url: str = MCP_ATLASSIAN_URL) -> None:
        self._mcp_url = mcp_url

    def _cred_args(self, credentials: JiraCredentials) -> dict:
        """Map JiraCredentials to mcp-atlassian argument keys."""
        return {
            "jira_url": credentials.jira_url,
            "jira_username": credentials.jira_email,   # jira_email → jira_username
            "jira_api_token": credentials.jira_token,   # jira_token → jira_api_token
        }

    async def add_comment(
        self, issue_key: str, body: str, credentials: JiraCredentials
    ) -> str:
        """Add a comment to a Jira issue. Returns the created comment ID."""
        args = {"issue_key": issue_key, "comment": body, **self._cred_args(credentials)}
        async with streamablehttp_client(self._mcp_url) as (read, write, _):
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
            "fields": {"description": description},
            **self._cred_args(credentials),
        }
        async with streamablehttp_client(self._mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("jira_update_issue", args)

    async def get_sprint_issues(
        self, project_key: str, credentials: JiraCredentials
    ) -> list[dict]:
        """Return open sprint issues for a project as [{key, summary, issue_type}]."""
        args = {
            "jql": f"project={project_key} AND sprint in openSprints()",
            "fields": ["summary", "issuetype"],
            **self._cred_args(credentials),
        }
        async with streamablehttp_client(self._mcp_url) as (read, write, _):
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
        args = {"query": display_name, **self._cred_args(credentials)}
        async with streamablehttp_client(self._mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("jira_get_users", args)
        parsed = json.loads(result.content[0].text)
        return str(parsed[0]["accountId"])

    async def assign_issue(
        self, issue_key: str, account_id: str, credentials: JiraCredentials
    ) -> None:
        """Assign a Jira issue to a user by accountId."""
        args = {
            "issue_key": issue_key,
            "account_id": account_id,
            **self._cred_args(credentials),
        }
        async with streamablehttp_client(self._mcp_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("jira_assign_issue", args)
