"""TDD tests for confluence_client.ConfluenceClient.

Tests (5 total):
1. test_create_page_posts_correct_payload - mock POST returns 200; asserts request body and return value
2. test_create_page_sets_basic_auth - assert Authorization header uses Basic auth with ("", token)
3. test_get_page_url_constructs_correctly - pure URL construction; no network call
4. test_publish_architecture_returns_page_url - mock POST 200; assert returned URL contains page id
5. test_publish_architecture_graceful_on_failure - mock POST 500; assert returns "" (no exception)

Uses respx for httpx.AsyncClient mocking; pytest-asyncio for async test functions.
"""

import base64
import os
from unittest.mock import MagicMock

import httpx
import pytest
import respx
from cryptography.fernet import Fernet

# Set env vars before any app imports.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)

from services.confluence_client import ConfluenceClient  # noqa: E402


CONFLUENCE_BASE = "https://confluence.example.com"
CONF_TOKEN = "confluence-token-plain"


def _make_client() -> ConfluenceClient:
    return ConfluenceClient(base_url=CONFLUENCE_BASE, token=CONF_TOKEN)


def _make_mock_project():
    """Return a mock Project with confluence credentials."""
    from cryptography.fernet import Fernet as _Fernet
    key = os.environ["ENCRYPTION_KEY"].encode()
    encrypted_token = _Fernet(key).encrypt(CONF_TOKEN.encode()).decode()

    p = MagicMock()
    p.id = 1
    p.project_key = "PROJ"
    p.jira_url = "https://jira.example.com"
    p.confluence_url = CONFLUENCE_BASE
    p.confluence_token = encrypted_token
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_page_posts_correct_payload():
    """Mock POST to Confluence returns 200; assert body payload and return dict."""
    response_body = {
        "id": "12345",
        "space": {"key": "PROJ"},
        "_links": {"webui": "/spaces/PROJ/pages/12345"},
    }
    respx.post(f"{CONFLUENCE_BASE}/wiki/rest/api/content").mock(
        return_value=httpx.Response(200, json=response_body)
    )

    client = _make_client()
    result = await client.create_page("PROJ", "Arch Options TICKET-1", "<h1>Options</h1>")

    # Assert the mock was called once
    assert respx.calls.call_count == 1
    # Assert request body contains expected fields
    request = respx.calls.last.request
    import json
    body = json.loads(request.content)
    assert body["type"] == "page"
    assert body["title"] == "Arch Options TICKET-1"
    assert body["body"]["storage"]["value"] == "<h1>Options</h1>"
    # Assert return value is the response dict
    assert result["id"] == "12345"


@pytest.mark.asyncio
@respx.mock
async def test_create_page_sets_basic_auth():
    """Assert Authorization header uses Basic auth encoding of (':token')."""
    response_body = {
        "id": "12345",
        "space": {"key": "PROJ"},
        "_links": {"webui": "/spaces/PROJ/pages/12345"},
    }
    respx.post(f"{CONFLUENCE_BASE}/wiki/rest/api/content").mock(
        return_value=httpx.Response(200, json=response_body)
    )

    client = _make_client()
    await client.create_page("PROJ", "Test Page", "<p>body</p>")

    request = respx.calls.last.request
    auth_header = request.headers.get("authorization", "")
    assert auth_header.startswith("Basic ")
    # Decode and verify it is ":confluence-token-plain"
    encoded = auth_header[len("Basic "):]
    decoded = base64.b64decode(encoded).decode()
    assert decoded == f":{CONF_TOKEN}"


def test_get_page_url_constructs_correctly():
    """get_page_url returns correct URL without making a network call.

    This is a synchronous test — get_page_url does not make any network calls.
    """
    client = _make_client()
    url = client.get_page_url("PROJ", "12345")
    assert url == f"{CONFLUENCE_BASE}/wiki/spaces/PROJ/pages/12345"


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_returns_page_url():
    """Mock POST returns page id '99'; publish_architecture returns URL containing '99'."""
    response_body = {
        "id": "99",
        "space": {"key": "PROJ"},
        "_links": {"webui": "/spaces/PROJ/pages/99"},
    }
    respx.post(f"{CONFLUENCE_BASE}/wiki/rest/api/content").mock(
        return_value=httpx.Response(200, json=response_body)
    )

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(mock_project, "TICKET-1", "arch text", ["<xml/>"])

    assert isinstance(result, str)
    assert len(result) > 0
    assert "/wiki/spaces/" in result
    assert "99" in result


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_graceful_on_failure():
    """Mock POST returns 500; publish_architecture returns '' (no exception raised)."""
    respx.post(f"{CONFLUENCE_BASE}/wiki/rest/api/content").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(mock_project, "TICKET-1", "arch text", ["<xml/>"])

    assert result == ""
