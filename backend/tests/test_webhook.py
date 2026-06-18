"""Tests for POST /webhook/jira-comment endpoint.

TDD RED phase: These tests are written before the implementation exists.
All tests should fail until models/webhook.py, routers/webhook.py, and
main.py are updated.
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

pytestmark = pytest.mark.asyncio

# Sample valid JiraCommentEvent payload
VALID_PAYLOAD = {
    "webhook_event": "comment_created",
    "issue": {
        "id": "10001",
        "key": "PROJ-1",
        "summary": "Feature X",
    },
    "comment": {
        "id": "20001",
        "body": "@hermes describe",
        "author": "alice",
    },
    "timestamp": 1718000000,
}

NO_MENTION_PAYLOAD = {
    "webhook_event": "comment_created",
    "issue": {
        "id": "10001",
        "key": "PROJ-2",
        "summary": "Feature Y",
    },
    "comment": {
        "id": "20002",
        "body": "Nice work team!",
        "author": "bob",
    },
    "timestamp": 1718000001,
}

MISSING_FIELD_PAYLOAD = {
    # Missing 'issue' — should trigger 422 Unprocessable Entity
    "webhook_event": "comment_created",
    "comment": {
        "id": "20003",
        "body": "@hermes describe",
        "author": "carol",
    },
    "timestamp": 1718000002,
}


@pytest.fixture
def app():
    from main import app as _app
    return _app


async def test_valid_webhook_returns_200(app):
    """Test 1: POST with valid JiraCommentEvent returns HTTP 200 and status received."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"


async def test_missing_required_field_returns_422(app):
    """Test 2: POST with missing required field returns HTTP 422."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=MISSING_FIELD_PAYLOAD)
    assert response.status_code == 422


async def test_no_mention_returns_ignored(app):
    """Test 3: POST where comment body has no @hermes mention returns action: ignored."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=NO_MENTION_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body.get("action") == "ignored"


async def test_hermes_mention_returns_non_ignored_action(app):
    """Test 4: POST where comment body contains @hermes describe returns action != ignored."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/jira-comment", json=VALID_PAYLOAD)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body.get("action") != "ignored"
    assert "routed_to" in body
