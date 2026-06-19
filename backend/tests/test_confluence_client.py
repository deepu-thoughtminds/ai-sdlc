"""Tests for confluence_client.ConfluenceClient.

Covers:
1. create_page payload + auth header (pre-existing)
2. get_page_url construction (pre-existing, no network call)
3. find_page — search CQL, returns None when no results
4. publish_architecture diagram template (is_complex=True) — six sections +
   drawio-xml block + viewer link
5. publish_architecture text-only template (is_complex=False) — four sections,
   no drawio-xml block
6. HTML-escaping of special characters in architecture text
7. find-or-update idempotency — second publish_architecture call for the same
   issue_key updates (PUT) instead of creating (POST)
8. update_page sends incremented version number
9. graceful degradation — any exception returns ""

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


def _mock_search_empty():
    """Mock the find_page search endpoint to return no results."""
    respx.get(f"{CONFLUENCE_BASE}/wiki/rest/api/content/search").mock(
        return_value=httpx.Response(200, json={"results": []})
    )


def _mock_search_found(page_id: str = "555", version: int = 3):
    """Mock the find_page search endpoint to return one existing page."""
    respx.get(f"{CONFLUENCE_BASE}/wiki/rest/api/content/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": page_id,
                        "version": {"number": version},
                    }
                ]
            },
        )
    )


def _mock_create(page_id: str = "12345"):
    respx.post(f"{CONFLUENCE_BASE}/wiki/rest/api/content").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": page_id,
                "space": {"key": "PROJ"},
                "_links": {"webui": f"/spaces/PROJ/pages/{page_id}"},
            },
        )
    )


def _mock_update(page_id: str = "555"):
    respx.put(f"{CONFLUENCE_BASE}/wiki/rest/api/content/{page_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": page_id,
                "space": {"key": "PROJ"},
                "_links": {"webui": f"/spaces/PROJ/pages/{page_id}"},
            },
        )
    )


# ---------------------------------------------------------------------------
# Pre-existing tests
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


# ---------------------------------------------------------------------------
# New tests — find_page
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_find_page_returns_none_when_no_results():
    """find_page returns None when the Confluence search API returns no results."""
    _mock_search_empty()

    client = _make_client()
    result = await client.find_page("PROJ", "Architecture: TICKET-1")

    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_find_page_returns_result_when_found():
    """find_page returns the first matching result dict when found."""
    _mock_search_found(page_id="555", version=3)

    client = _make_client()
    result = await client.find_page("PROJ", "Architecture: TICKET-1")

    assert result is not None
    assert result["id"] == "555"
    assert result["version"]["number"] == 3


# ---------------------------------------------------------------------------
# New tests — publish_architecture templates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_diagram_template_contains_drawio_block():
    """is_complex=True produces all six headings + drawio-xml block + viewer link."""
    _mock_search_empty()
    _mock_create(page_id="12345")

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary="Summary text",
        approach="Approach text",
        key_decisions="Decisions text",
        risks="Risks text",
        is_complex=True,
        component_breakdown="Component breakdown text",
        integration_points="Integration points text",
        diagram_xml="<mxGraphModel/>",
        viewer_url="https://app.diagrams.net/?xml=abc",
    )

    assert isinstance(result, str)
    assert len(result) > 0

    request = respx.calls.last.request
    import json
    body = json.loads(request.content)
    body_html = body["body"]["storage"]["value"]

    for heading in (
        "Summary",
        "Approach",
        "Component Breakdown",
        "Integration Points",
        "Key Decisions",
        "Risks",
    ):
        assert f">{heading}<" in body_html

    assert '<pre class="drawio-xml">' in body_html
    assert "<mxGraphModel/>" in body_html
    assert "https://app.diagrams.net/?xml=abc" in body_html


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_text_only_template_excludes_diagram_block():
    """is_complex=False produces exactly four text-only headings, no drawio-xml block."""
    _mock_search_empty()
    _mock_create(page_id="12345")

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary="Summary text",
        approach="Approach text",
        key_decisions="Decisions text",
        risks="Risks text",
        is_complex=False,
    )

    assert isinstance(result, str)
    assert len(result) > 0

    request = respx.calls.last.request
    import json
    body = json.loads(request.content)
    body_html = body["body"]["storage"]["value"]

    for heading in ("Summary", "Approach", "Key Decisions", "Risks"):
        assert f">{heading}<" in body_html

    for heading in ("Component Breakdown", "Integration Points"):
        assert f">{heading}<" not in body_html

    assert "drawio-xml" not in body_html


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_escapes_html_special_chars():
    """Architecture text containing HTML special chars is escaped, never raw."""
    _mock_search_empty()
    _mock_create(page_id="12345")

    client = _make_client()
    mock_project = _make_mock_project()

    dangerous = '<script>alert("xss")</script> & more <b>bold</b>'

    await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary=dangerous,
        approach="Approach text",
        key_decisions="Decisions text",
        risks="Risks text",
        is_complex=False,
    )

    request = respx.calls.last.request
    import json
    body = json.loads(request.content)
    body_html = body["body"]["storage"]["value"]

    assert "<script>" not in body_html
    assert "&lt;script&gt;" in body_html
    assert "&amp;" in body_html
    assert "&quot;" in body_html or "&#x27;" in body_html or "xss" in body_html


# ---------------------------------------------------------------------------
# New tests — find-or-update idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_creates_when_no_existing_page():
    """publish_architecture calls create_page (POST) when find_page returns None."""
    _mock_search_empty()
    _mock_create(page_id="12345")

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary="Summary",
        approach="Approach",
        key_decisions="Decisions",
        risks="Risks",
    )

    assert "12345" in result
    post_calls = [c for c in respx.calls if c.request.method == "POST"]
    put_calls = [c for c in respx.calls if c.request.method == "PUT"]
    assert len(post_calls) == 1
    assert len(put_calls) == 0


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_updates_existing_page_instead_of_creating():
    """Second publish_architecture call for same issue_key updates (PUT), not creates (POST)."""
    _mock_search_found(page_id="555", version=3)
    _mock_update(page_id="555")

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary="Updated summary",
        approach="Updated approach",
        key_decisions="Updated decisions",
        risks="Updated risks",
    )

    assert "555" in result

    search_calls = [
        c for c in respx.calls if c.request.method == "GET" and "search" in str(c.request.url)
    ]
    post_calls = [c for c in respx.calls if c.request.method == "POST"]
    put_calls = [c for c in respx.calls if c.request.method == "PUT"]

    assert len(search_calls) == 1
    assert len(post_calls) == 0
    assert len(put_calls) == 1

    # The search call must happen before the update call
    search_call = search_calls[0]
    put_call = put_calls[0]
    assert respx.calls.index(search_call) < respx.calls.index(put_call)


@pytest.mark.asyncio
@respx.mock
async def test_update_page_sends_incremented_version():
    """update_page PUT payload contains version.number = current_version + 1."""
    _mock_search_found(page_id="555", version=3)
    _mock_update(page_id="555")

    client = _make_client()
    mock_project = _make_mock_project()

    await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary="Summary",
        approach="Approach",
        key_decisions="Decisions",
        risks="Risks",
    )

    put_call = next(c for c in respx.calls if c.request.method == "PUT")
    import json
    body = json.loads(put_call.request.content)
    assert body["version"]["number"] == 4


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_graceful_on_failure():
    """Mock search succeeds, create returns 500; publish_architecture returns '' (no exception)."""
    _mock_search_empty()
    respx.post(f"{CONFLUENCE_BASE}/wiki/rest/api/content").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary="Summary",
        approach="Approach",
        key_decisions="Decisions",
        risks="Risks",
    )

    assert result == ""


@pytest.mark.asyncio
@respx.mock
async def test_publish_architecture_graceful_on_search_failure():
    """If find_page (search) itself raises, publish_architecture returns ''."""
    respx.get(f"{CONFLUENCE_BASE}/wiki/rest/api/content/search").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = _make_client()
    mock_project = _make_mock_project()

    result = await client.publish_architecture(
        mock_project,
        "TICKET-1",
        summary="Summary",
        approach="Approach",
        key_decisions="Decisions",
        risks="Risks",
    )

    assert result == ""
