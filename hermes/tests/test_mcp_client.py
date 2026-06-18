"""Unit tests for HermesMCPClient — all mocked, no live network calls."""
import json
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from hermes.mcp_client import HermesMCPClient, JiraCredentials

TEST_CREDS = JiraCredentials(
    jira_url="https://test.atlassian.net",
    jira_email="user@test.com",
    jira_token="token123",
)


def make_mock_session(call_tool_return_text: str) -> AsyncMock:
    """Build a mock MCP session with a configured call_tool result."""
    session = AsyncMock()
    session.initialize = AsyncMock()
    result = MagicMock()
    result.content = [MagicMock(text=call_tool_return_text)]
    session.call_tool = AsyncMock(return_value=result)
    return session


def make_mcp_patches(call_tool_return_text: str):
    """Return context managers that patch streamablehttp_client and ClientSession.

    streamablehttp_client is patched to return (read_mock, write_mock, None).
    ClientSession is patched so __aenter__ returns the mock session.
    """
    mock_session = make_mock_session(call_tool_return_text)

    read_mock = AsyncMock()
    write_mock = AsyncMock()

    @asynccontextmanager
    async def fake_streamable(url):
        yield read_mock, write_mock, None

    # ClientSession async context manager: __aenter__ returns mock_session
    mock_cs_instance = AsyncMock()
    mock_cs_instance.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cs_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cs_class = MagicMock(return_value=mock_cs_instance)

    return fake_streamable, mock_cs_class, mock_session


# ---------------------------------------------------------------------------
# 1. add_comment — correct tool name
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_comment_calls_correct_tool():
    """add_comment() calls jira_add_comment with issue_key, comment, and credentials."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(
        json.dumps({"id": "99"})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        await client.add_comment("TS-1", "Hello Jira", TEST_CREDS)

    mock_session.call_tool.assert_called_once()
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "jira_add_comment"
    assert args["issue_key"] == "TS-1"
    assert args["comment"] == "Hello Jira"
    assert "jira_url" in args
    assert "jira_username" in args
    assert "jira_api_token" in args


# ---------------------------------------------------------------------------
# 2. add_comment — returns comment ID
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_comment_returns_comment_id():
    """add_comment() returns the string comment ID from the tool result."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(
        json.dumps({"id": "12345"})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.add_comment("TS-1", "body", TEST_CREDS)

    assert result == "12345"


# ---------------------------------------------------------------------------
# 3. add_comment — credential field mapping
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_comment_maps_credentials():
    """jira_email → jira_username and jira_token → jira_api_token in tool args."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(
        json.dumps({"id": "1"})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        await client.add_comment("TS-2", "mapped?", TEST_CREDS)

    _, args = mock_session.call_tool.call_args[0]
    assert args["jira_username"] == TEST_CREDS.jira_email
    assert args["jira_api_token"] == TEST_CREDS.jira_token
    assert args["jira_url"] == TEST_CREDS.jira_url
    # Raw field names must NOT be present
    assert "jira_email" not in args
    assert "jira_token" not in args


# ---------------------------------------------------------------------------
# 4. update_description — correct tool name and fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_description_calls_correct_tool():
    """update_description() calls jira_update_issue with fields={'description': ...}."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(
        json.dumps({})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.update_description("TS-3", "new desc", TEST_CREDS)

    assert result is None
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "jira_update_issue"
    assert args["fields"] == {"description": "new desc"}
    assert args["issue_key"] == "TS-3"


# ---------------------------------------------------------------------------
# 5. get_sprint_issues — returns normalised list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_sprint_issues_returns_list():
    """get_sprint_issues() returns [{key, summary, issue_type}] from jira_search."""
    payload = json.dumps({
        "issues": [
            {
                "key": "TS-1",
                "fields": {
                    "summary": "Do work",
                    "issuetype": {"name": "Story"},
                },
            }
        ]
    })
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        issues = await client.get_sprint_issues("TS", TEST_CREDS)

    assert issues == [{"key": "TS-1", "summary": "Do work", "issue_type": "Story"}]
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "jira_search"
    assert "openSprints()" in args["jql"]


# ---------------------------------------------------------------------------
# 6. lookup_user — returns accountId
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_user_returns_account_id():
    """lookup_user() returns the accountId string from the first result."""
    payload = json.dumps([{"accountId": "abc123", "displayName": "Alice"}])
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        account_id = await client.lookup_user("Alice", TEST_CREDS)

    assert account_id == "abc123"
    tool_name, _ = mock_session.call_tool.call_args[0]
    assert tool_name == "jira_get_users"


# ---------------------------------------------------------------------------
# 7. assign_issue — correct tool name and account_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_assign_issue_calls_correct_tool():
    """assign_issue() calls jira_assign_issue with account_id in args, returns None."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(
        json.dumps({})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.assign_issue("TS-4", "abc123", TEST_CREDS)

    assert result is None
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "jira_assign_issue"
    assert args["account_id"] == "abc123"
    assert args["issue_key"] == "TS-4"
