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
