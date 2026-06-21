"""Integration tests for hermes/server.py — all HermesMCPClient calls mocked."""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock

from hermes.server import app, get_mcp_client

BASE_CREDS = {
    "jira_url": "https://test.atlassian.net",
    "jira_email": "user@test.com",
    "jira_token": "token123",
}


def make_mock_client():
    client = AsyncMock()
    client.add_comment = AsyncMock(return_value="12345")
    client.update_description = AsyncMock(return_value=None)
    client.get_sprint_issues = AsyncMock(
        return_value=[{"key": "TS-1", "summary": "Do work", "issue_type": "Story"}]
    )
    client.lookup_user = AsyncMock(return_value="acc-99")
    client.assign_issue = AsyncMock(return_value=None)
    # Jira comment stubs
    client.get_comments = AsyncMock(
        return_value=[{"id": "c1", "body": "A comment", "author": {"displayName": "Alice"}}]
    )
    # Confluence stubs
    client.create_confluence_page = AsyncMock(
        return_value={"id": "9999", "space": {"key": "PROJ"}}
    )
    client.update_confluence_page = AsyncMock(
        return_value={"id": "9999", "version": {"number": 4}}
    )
    client.find_confluence_page = AsyncMock(
        return_value={"id": "9999", "version": {"number": 3}}
    )
    client.get_confluence_page = AsyncMock(
        return_value="<p>Architecture content here</p>"
    )
    return client


@pytest.fixture(autouse=True)
def clear_overrides():
    """Ensure dependency overrides are cleaned up after each test."""
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_post_comment_returns_comment_id():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/jira/comment", json={**BASE_CREDS, "issue_key": "TS-1", "body": "Hello"})
    assert resp.status_code == 200
    assert resp.json() == {"comment_id": "12345"}
    mock_client.add_comment.assert_called_once()


@pytest.mark.asyncio
async def test_put_description_returns_empty():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.put("/jira/description", json={**BASE_CREDS, "issue_key": "TS-1", "description": "new desc"})
    assert resp.status_code == 200
    assert resp.json() == {}
    mock_client.update_description.assert_called_once()


@pytest.mark.asyncio
async def test_post_sprint_backlog_returns_list():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/jira/sprint-backlog", json={**BASE_CREDS, "project_key": "TS"})
    assert resp.status_code == 200
    assert resp.json() == [{"key": "TS-1", "summary": "Do work", "issue_type": "Story"}]


@pytest.mark.asyncio
async def test_post_assign_returns_account_id():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/jira/assign", json={**BASE_CREDS, "issue_key": "TS-1", "display_name": "Alice"})
    assert resp.status_code == 200
    assert resp.json() == {"account_id": "acc-99"}
    mock_client.lookup_user.assert_called_once()
    mock_client.assign_issue.assert_called_once()


@pytest.mark.asyncio
async def test_post_comment_500_on_client_error():
    mock_client = make_mock_client()
    mock_client.add_comment = AsyncMock(side_effect=RuntimeError("mcp down"))
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/jira/comment", json={**BASE_CREDS, "issue_key": "TS-1", "body": "Hello"})
    assert resp.status_code == 500
    assert "mcp down" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_post_assign_calls_lookup_then_assign():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post("/jira/assign", json={**BASE_CREDS, "issue_key": "TS-1", "display_name": "Alice"})
    # lookup_user returns "acc-99"; assign_issue must be called with that account_id
    assign_call = mock_client.assign_issue.call_args
    assert assign_call.args[1] == "acc-99" or assign_call.kwargs.get("account_id") == "acc-99"


# ---------------------------------------------------------------------------
# Confluence endpoint tests
# ---------------------------------------------------------------------------

BASE_CONF_CREDS = {
    "confluence_url": "https://confluence.atlassian.net",
    "confluence_email": "conf@test.com",
    "confluence_token": "conf-token-456",
}


@pytest.mark.asyncio
async def test_post_confluence_page_returns_created_page():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    payload = {
        **BASE_CONF_CREDS,
        "space_key": "PROJ",
        "title": "Architecture: TICKET-1",
        "body_html": "<h1>Architecture</h1>",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/confluence/page", json=payload)
    assert resp.status_code == 200
    assert resp.json()["id"] == "9999"
    mock_client.create_confluence_page.assert_called_once()


@pytest.mark.asyncio
async def test_put_confluence_page_returns_updated_page():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    payload = {
        **BASE_CONF_CREDS,
        "title": "Architecture: TICKET-1",
        "body_html": "<h1>Updated</h1>",
        "version": 4,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.put("/confluence/page/9999", json=payload)
    assert resp.status_code == 200
    assert resp.json()["id"] == "9999"
    mock_client.update_confluence_page.assert_called_once()


@pytest.mark.asyncio
async def test_get_confluence_search_returns_result_or_empty_dict():
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    params = {
        **BASE_CONF_CREDS,
        "space_key": "PROJ",
        "title": "Architecture: TICKET-1",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/confluence/search", params=params)
    assert resp.status_code == 200
    body = resp.json()
    # When find_confluence_page returns a dict, server returns it as-is
    assert body["id"] == "9999"
    mock_client.find_confluence_page.assert_called_once()


@pytest.mark.asyncio
async def test_get_confluence_search_returns_empty_dict_when_not_found():
    mock_client = make_mock_client()
    mock_client.find_confluence_page = AsyncMock(return_value=None)
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    params = {
        **BASE_CONF_CREDS,
        "space_key": "PROJ",
        "title": "Nonexistent Page",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/confluence/search", params=params)
    assert resp.status_code == 200
    assert resp.json() == {}


@pytest.mark.asyncio
async def test_post_confluence_page_500_on_client_error():
    mock_client = make_mock_client()
    mock_client.create_confluence_page = AsyncMock(side_effect=RuntimeError("mcp down"))
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    payload = {
        **BASE_CONF_CREDS,
        "space_key": "PROJ",
        "title": "Architecture: TICKET-1",
        "body_html": "<h1>Architecture</h1>",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/confluence/page", json=payload)
    assert resp.status_code == 500
    assert "mcp down" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /jira/comments tests (Phase 16 Plan 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_get_comments_returns_comment_list():
    """POST /jira/comments returns the comment list from get_comments()."""
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/jira/comments",
            json={**BASE_CREDS, "issue_key": "TS-1"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["id"] == "c1"


@pytest.mark.asyncio
async def test_post_get_comments_calls_get_comments_with_issue_key():
    """POST /jira/comments passes issue_key to get_comments()."""
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.post(
            "/jira/comments",
            json={**BASE_CREDS, "issue_key": "TS-99"},
        )
    mock_client.get_comments.assert_called_once()
    call_args = mock_client.get_comments.call_args
    assert call_args.args[0] == "TS-99" or call_args.kwargs.get("issue_key") == "TS-99"


@pytest.mark.asyncio
async def test_post_get_comments_returns_500_on_client_error():
    """POST /jira/comments returns 500 when get_comments() raises."""
    mock_client = make_mock_client()
    mock_client.get_comments = AsyncMock(side_effect=RuntimeError("mcp down"))
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/jira/comments",
            json={**BASE_CREDS, "issue_key": "TS-1"},
        )
    assert resp.status_code == 500
    assert "mcp down" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /confluence/page/{page_id} tests (Phase 16 Plan 01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_confluence_page_returns_body_string():
    """GET /confluence/page/{page_id} returns body content as plain string."""
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/confluence/page/42",
            params={**BASE_CONF_CREDS},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["body"] == "<p>Architecture content here</p>"


@pytest.mark.asyncio
async def test_get_confluence_page_calls_get_confluence_page_with_page_id():
    """GET /confluence/page/{page_id} passes page_id to get_confluence_page()."""
    mock_client = make_mock_client()
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.get(
            "/confluence/page/99",
            params={**BASE_CONF_CREDS},
        )
    mock_client.get_confluence_page.assert_called_once()
    call_args = mock_client.get_confluence_page.call_args
    assert call_args.args[0] == "99" or call_args.kwargs.get("page_id") == "99"


@pytest.mark.asyncio
async def test_get_confluence_page_returns_500_on_client_error():
    """GET /confluence/page/{page_id} returns 500 when get_confluence_page() raises."""
    mock_client = make_mock_client()
    mock_client.get_confluence_page = AsyncMock(side_effect=RuntimeError("mcp down"))
    app.dependency_overrides[get_mcp_client] = lambda: mock_client
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/confluence/page/42",
            params={**BASE_CONF_CREDS},
        )
    assert resp.status_code == 500
    assert "mcp down" in resp.json()["detail"]
