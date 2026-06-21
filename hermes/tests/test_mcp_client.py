"""Unit tests for HermesMCPClient — all mocked, no live network calls."""
import json
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from hermes.mcp_client import HermesMCPClient, JiraCredentials, ConfluenceCredentials

TEST_CREDS = JiraCredentials(
    jira_url="https://test.atlassian.net",
    jira_email="user@test.com",
    jira_token="token123",
)

TEST_CONFLUENCE_CREDS = ConfluenceCredentials(
    confluence_url="https://confluence.atlassian.net",
    confluence_email="conf@test.com",
    confluence_token="conf-token-456",
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
    async def fake_streamable(url, **kwargs):
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


# ---------------------------------------------------------------------------
# Confluence test helpers
# ---------------------------------------------------------------------------


def make_mcp_patches_kw(call_tool_return_text: str):
    """Variant of make_mcp_patches that accepts keyword args (e.g. headers=...) to
    streamablehttp_client — required because the Confluence methods pass credentials
    as keyword arguments while the existing fake_streamable only accepts positional url.
    """
    mock_session = make_mock_session(call_tool_return_text)

    read_mock = AsyncMock()
    write_mock = AsyncMock()

    @asynccontextmanager
    async def fake_streamable_kw(url, **kwargs):
        yield read_mock, write_mock, None

    mock_cs_instance = AsyncMock()
    mock_cs_instance.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cs_instance.__aexit__ = AsyncMock(return_value=False)

    mock_cs_class = MagicMock(return_value=mock_cs_instance)

    return fake_streamable_kw, mock_cs_class, mock_session


# ---------------------------------------------------------------------------
# Confluence method tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_confluence_page_calls_correct_tool():
    """create_confluence_page() calls confluence_create_page with space_key/title/content."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches_kw(
        json.dumps({"id": "9999"})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.create_confluence_page(
            "PROJ", "My Page", "<p>body</p>", TEST_CONFLUENCE_CREDS
        )

    assert result == {"id": "9999"}
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "confluence_create_page"
    assert args["space_key"] == "PROJ"
    assert args["title"] == "My Page"
    assert args["content"] == "<p>body</p>"


@pytest.mark.asyncio
async def test_find_confluence_page_returns_first_result():
    """find_confluence_page() returns the first item from a list result."""
    page = {"id": "9999", "version": {"number": 2}}
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches_kw(
        json.dumps([page])
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.find_confluence_page("PROJ", "My Page", TEST_CONFLUENCE_CREDS)

    # find_confluence_page returns only {"id"} — version is not needed (update_page auto-manages it)
    assert result == {"id": "9999"}
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "confluence_search"
    assert "PROJ" in args["query"]
    assert "My Page" in args["query"]
    assert args["limit"] == 1


@pytest.mark.asyncio
async def test_find_confluence_page_returns_none_when_empty():
    """find_confluence_page() returns None when confluence_search returns an empty list."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches_kw(
        json.dumps([])
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.find_confluence_page("PROJ", "Nonexistent", TEST_CONFLUENCE_CREDS)

    assert result is None


@pytest.mark.asyncio
async def test_update_confluence_page_calls_correct_tool():
    """update_confluence_page() calls confluence_update_page with page_id and version."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches_kw(
        json.dumps({"id": "9999", "version": {"number": 4}})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.update_confluence_page(
            "9999", "My Page", "<p>updated</p>", 4, TEST_CONFLUENCE_CREDS
        )

    assert result["id"] == "9999"
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "confluence_update_page"
    assert args["page_id"] == "9999"
    assert "version" not in args  # tool auto-manages version; not forwarded


@pytest.mark.asyncio
async def test_confluence_cred_headers_uses_distinct_header_name():
    """_confluence_cred_headers uses x-atlassian-confluence-url, not x-atlassian-jira-url (T-Q01-01)."""
    client = HermesMCPClient(mcp_url="http://fake:9000/sse")
    headers = client._confluence_cred_headers(TEST_CONFLUENCE_CREDS)

    assert "x-atlassian-confluence-url" in headers
    assert "x-atlassian-jira-url" not in headers
    assert headers["x-atlassian-confluence-url"] == TEST_CONFLUENCE_CREDS.confluence_url
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


# ---------------------------------------------------------------------------
# get_comments tests (Phase 16 Plan 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_comments_calls_correct_tool():
    """get_comments() calls jira_get_issue with comment expansion."""
    payload = json.dumps({
        "fields": {
            "comment": {
                "comments": [
                    {"id": "c1", "body": "First comment", "author": {"displayName": "Alice"}},
                ]
            }
        }
    })
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_comments("TS-1", TEST_CREDS)

    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "jira_get_issue"
    assert args["issue_key"] == "TS-1"
    assert "comment" in args.get("fields", "")


@pytest.mark.asyncio
async def test_get_comments_returns_flat_list():
    """get_comments() returns a flat list[dict] from the comment envelope."""
    payload = json.dumps({
        "fields": {
            "comment": {
                "comments": [
                    {"id": "c1", "body": "First comment", "author": {"displayName": "Alice"}},
                    {"id": "c2", "body": "Second comment", "author": {"displayName": "Bob"}},
                ]
            }
        }
    })
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_comments("TS-1", TEST_CREDS)

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["id"] == "c1"
    assert result[1]["id"] == "c2"


@pytest.mark.asyncio
async def test_get_comments_returns_empty_list_when_no_comments():
    """get_comments() returns [] when issue has no comments."""
    payload = json.dumps({
        "fields": {
            "comment": {"comments": []}
        }
    })
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_comments("TS-1", TEST_CREDS)

    assert result == []


@pytest.mark.asyncio
async def test_get_comments_flattens_adf_body_to_plain_text():
    """get_comments() converts an ADF dict body into a plain text string.

    Regression test for scrum54-dev-pipeline-missing-arch-url: Jira Cloud
    REST API v3 returns comment.body as an ADF document, not a plain string.
    Downstream consumers (find_latest_architecture_url) require a plain
    string body or they silently skip the comment.
    """
    adf_body = {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Architecture published: "},
                    {
                        "type": "text",
                        "text": "https://team.atlassian.net/wiki/spaces/PROJ/pages/123",
                    },
                ],
            }
        ],
    }
    payload = json.dumps({
        "fields": {
            "comment": {
                "comments": [
                    {"id": "c1", "body": adf_body, "author": {"displayName": "Bot"}},
                ]
            }
        }
    })
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_comments("TS-1", TEST_CREDS)

    assert isinstance(result[0]["body"], str)
    assert "https://team.atlassian.net/wiki/spaces/PROJ/pages/123" in result[0]["body"]


@pytest.mark.asyncio
async def test_get_comments_leaves_plain_string_body_unchanged():
    """get_comments() does not alter a comment whose body is already a string."""
    payload = json.dumps({
        "fields": {
            "comment": {
                "comments": [
                    {"id": "c1", "body": "Plain text comment", "author": {"displayName": "Alice"}},
                ]
            }
        }
    })
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_comments("TS-1", TEST_CREDS)

    assert result[0]["body"] == "Plain text comment"


@pytest.mark.asyncio
async def test_get_comments_uses_jira_cred_headers():
    """get_comments() uses Jira credentials (not Confluence headers)."""
    payload = json.dumps({"fields": {"comment": {"comments": []}}})
    headers_used = {}

    @asynccontextmanager
    async def capturing_streamable(url, **kwargs):
        headers_used.update(kwargs.get("headers", {}))
        mock_session = make_mock_session(payload)
        yield AsyncMock(), AsyncMock(), None

    mock_cs_instance = AsyncMock()
    mock_cs_instance.__aenter__ = AsyncMock(return_value=make_mock_session(payload))
    mock_cs_instance.__aexit__ = AsyncMock(return_value=False)
    mock_cs_class = MagicMock(return_value=mock_cs_instance)

    with patch("hermes.mcp_client.streamablehttp_client", capturing_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        await client.get_comments("TS-1", TEST_CREDS)

    assert "x-atlassian-jira-url" in headers_used
    assert "x-atlassian-confluence-url" not in headers_used


# ---------------------------------------------------------------------------
# get_confluence_page tests (Phase 16 Plan 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_confluence_page_calls_correct_tool():
    """get_confluence_page() calls confluence_get_page with page_id."""
    payload = json.dumps({"id": "42", "body": {"storage": {"value": "<p>content</p>"}}})
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches_kw(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_confluence_page("42", TEST_CONFLUENCE_CREDS)

    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "confluence_get_page"
    assert args["page_id"] == "42"


@pytest.mark.asyncio
async def test_get_confluence_page_returns_plain_string_body():
    """get_confluence_page() returns a plain string body, not the raw MCP envelope."""
    body_text = "<p>Architecture diagram here</p>"
    payload = json.dumps({"id": "42", "body": {"storage": {"value": body_text}}})
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches_kw(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_confluence_page("42", TEST_CONFLUENCE_CREDS)

    assert isinstance(result, str)
    assert result == body_text


@pytest.mark.asyncio
async def test_get_confluence_page_returns_empty_string_when_no_body():
    """get_confluence_page() returns '' when body/storage/value is missing."""
    payload = json.dumps({"id": "42"})
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches_kw(payload)
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.get_confluence_page("42", TEST_CONFLUENCE_CREDS)

    assert result == ""


@pytest.mark.asyncio
async def test_get_confluence_page_uses_confluence_cred_headers():
    """get_confluence_page() uses Confluence credentials (not Jira headers)."""
    payload = json.dumps({"id": "42", "body": {"storage": {"value": ""}}})
    headers_used = {}

    @asynccontextmanager
    async def capturing_streamable(url, **kwargs):
        headers_used.update(kwargs.get("headers", {}))
        mock_session = make_mock_session(payload)
        yield AsyncMock(), AsyncMock(), None

    mock_cs_instance = AsyncMock()
    mock_cs_instance.__aenter__ = AsyncMock(return_value=make_mock_session(payload))
    mock_cs_instance.__aexit__ = AsyncMock(return_value=False)
    mock_cs_class = MagicMock(return_value=mock_cs_instance)

    with patch("hermes.mcp_client.streamablehttp_client", capturing_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        await client.get_confluence_page("42", TEST_CONFLUENCE_CREDS)

    assert "x-atlassian-confluence-url" in headers_used
    assert "x-atlassian-jira-url" not in headers_used


# ---------------------------------------------------------------------------
# Phase 17 Plan 01: transition_issue tests (PRMERGE-02)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transition_issue_calls_correct_tool():
    """transition_issue() calls jira_transition_issue with issue_key and status."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(
        json.dumps({"result": "ok"})
    )
    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.transition_issue("PROJ-1", "Done", TEST_CREDS)

    assert result is True
    mock_session.call_tool.assert_called_once()
    tool_name, args = mock_session.call_tool.call_args[0]
    assert tool_name == "jira_transition_issue"
    assert args["issue_key"] == "PROJ-1"
    assert args["status"] == "Done"


@pytest.mark.asyncio
async def test_transition_issue_returns_false_on_exception():
    """transition_issue() catches any exception from call_tool and returns False."""
    fake_streamable, mock_cs_class, mock_session = make_mcp_patches(
        json.dumps({"result": "ok"})
    )
    mock_session.call_tool = AsyncMock(side_effect=Exception("invalid transition"))

    with patch("hermes.mcp_client.streamablehttp_client", fake_streamable), \
         patch("hermes.mcp_client.ClientSession", mock_cs_class):
        client = HermesMCPClient(mcp_url="http://fake:9000/sse")
        result = await client.transition_issue("PROJ-1", "InvalidStatus", TEST_CREDS)

    assert result is False
