"""Unit tests for backend/services/hermes_client.py using respx to mock httpx."""
import os
import pytest
import httpx
import respx

from services.hermes_client import (
    post_comment,
    post_sprint_backlog,
    post_assign,
    put_description,
    create_confluence_page,
    update_confluence_page,
    find_confluence_page,
)
import services.hermes_client as _hermes_client_mod

BASE = _hermes_client_mod.HERMES_BASE_URL


@pytest.mark.asyncio
@respx.mock
async def test_post_comment_returns_dict():
    respx.post(f"{BASE}/jira/comment").mock(
        return_value=httpx.Response(200, json={"comment_id": "c123"})
    )
    result = await post_comment("https://x.atlassian.net", "u@x.com", "tok", "TS-1", "Hello")
    assert result == {"comment_id": "c123"}


@pytest.mark.asyncio
@respx.mock
async def test_put_description_returns_empty_on_204():
    respx.put(f"{BASE}/jira/description").mock(
        return_value=httpx.Response(204, content=b"")
    )
    result = await put_description("https://x.atlassian.net", "u@x.com", "tok", "TS-1", "desc")
    assert result == {}


@pytest.mark.asyncio
@respx.mock
async def test_post_sprint_backlog_returns_list():
    data = [{"key": "PROJ-1", "summary": "S", "issue_type": "Story"}]
    respx.post(f"{BASE}/jira/sprint-backlog").mock(
        return_value=httpx.Response(200, json=data)
    )
    result = await post_sprint_backlog("https://x.atlassian.net", "u@x.com", "tok", "PROJ")
    assert result == data


@pytest.mark.asyncio
@respx.mock
async def test_post_sprint_backlog_returns_empty_on_connect_error():
    respx.post(f"{BASE}/jira/sprint-backlog").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = await post_sprint_backlog("https://x.atlassian.net", "u@x.com", "tok", "PROJ")
    assert result == []


@pytest.mark.asyncio
@respx.mock
async def test_post_sprint_backlog_returns_empty_on_http_500():
    respx.post(f"{BASE}/jira/sprint-backlog").mock(
        return_value=httpx.Response(500, json={"error": "fail"})
    )
    result = await post_sprint_backlog("https://x.atlassian.net", "u@x.com", "tok", "PROJ")
    assert result == []


@pytest.mark.asyncio
@respx.mock
async def test_post_assign_returns_account_id():
    respx.post(f"{BASE}/jira/assign").mock(
        return_value=httpx.Response(200, json={"account_id": "ACC1"})
    )
    result = await post_assign("https://x.atlassian.net", "u@x.com", "tok", "TS-1", "Alice")
    assert result == "ACC1"


@pytest.mark.asyncio
@respx.mock
async def test_post_assign_raises_on_http_500():
    respx.post(f"{BASE}/jira/assign").mock(
        return_value=httpx.Response(500, json={})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await post_assign("https://x.atlassian.net", "u@x.com", "tok", "TS-1", "Alice")


# ---------------------------------------------------------------------------
# Confluence functions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_confluence_page_returns_dict():
    page = {"id": "9999", "space": {"key": "PROJ"}}
    respx.post(f"{BASE}/confluence/page").mock(
        return_value=httpx.Response(200, json=page)
    )
    result = await create_confluence_page(
        "https://conf.example.com", "u@x.com", "tok", "PROJ", "My Page", "<p>body</p>"
    )
    assert result == page


@pytest.mark.asyncio
@respx.mock
async def test_update_confluence_page_returns_dict():
    page = {"id": "9999", "version": {"number": 4}}
    respx.put(f"{BASE}/confluence/page/9999").mock(
        return_value=httpx.Response(200, json=page)
    )
    result = await update_confluence_page(
        "https://conf.example.com", "u@x.com", "tok", "9999", "My Page", "<p>body</p>", 4
    )
    assert result == page


@pytest.mark.asyncio
@respx.mock
async def test_find_confluence_page_returns_dict_when_found():
    page = {"id": "9999", "version": {"number": 2}}
    respx.get(f"{BASE}/confluence/search").mock(
        return_value=httpx.Response(200, json=page)
    )
    result = await find_confluence_page(
        "https://conf.example.com", "u@x.com", "tok", "PROJ", "My Page"
    )
    assert result == page


@pytest.mark.asyncio
@respx.mock
async def test_find_confluence_page_returns_none_when_hermes_returns_empty_dict():
    """hermes returns {} when not found — find_confluence_page must translate to None."""
    respx.get(f"{BASE}/confluence/search").mock(
        return_value=httpx.Response(200, json={})
    )
    result = await find_confluence_page(
        "https://conf.example.com", "u@x.com", "tok", "PROJ", "My Page"
    )
    assert result is None
