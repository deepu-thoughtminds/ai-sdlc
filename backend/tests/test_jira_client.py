"""TDD tests for JiraClient service.

Tests (4 total):
1. test_get_sprint_backlog_returns_issues - mocked board/sprint/issue endpoint; returns list of dicts
2. test_get_sprint_backlog_no_active_sprint - 404 on active sprint; returns empty list
3. test_get_issue_returns_dict - mocked GET /rest/api/3/issue/{key}; returns dict with 'key' and 'fields'
4. test_jira_client_uses_auth_header - assert Authorization header is Basic base64(email:token)

Uses respx for httpx mocking.
"""

import base64

import respx
import httpx
import pytest

from services.jira_client import JiraClient


JIRA_URL = "https://test.atlassian.net"
TOKEN = "my-jira-api-token"
EMAIL = "user@example.com"


def _make_client(email: str = EMAIL) -> JiraClient:
    return JiraClient(jira_url=JIRA_URL, token=TOKEN, email=email)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@respx.mock
def test_get_sprint_backlog_returns_issues():
    """Mock board/sprint/issue endpoints; assert returns list with 'key', 'summary', 'issue_type'."""
    board_id = 1
    sprint_id = 42

    # Step 1: GET board list from project_key
    respx.get(f"{JIRA_URL}/rest/agile/1.0/board").mock(
        return_value=httpx.Response(200, json={"values": [{"id": board_id}]})
    )
    # Step 2: GET active sprint for board
    respx.get(f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/sprint").mock(
        return_value=httpx.Response(
            200,
            json={"values": [{"id": sprint_id, "state": "active"}]},
        )
    )
    # Step 3: GET issues in sprint
    respx.get(f"{JIRA_URL}/rest/agile/1.0/sprint/{sprint_id}/issue").mock(
        return_value=httpx.Response(
            200,
            json={
                "issues": [
                    {
                        "key": "PROJ-1",
                        "fields": {
                            "summary": "Add login feature",
                            "issuetype": {"name": "Story"},
                        },
                    },
                    {
                        "key": "PROJ-2",
                        "fields": {
                            "summary": "Fix bug in auth",
                            "issuetype": {"name": "Bug"},
                        },
                    },
                ]
            },
        )
    )

    client = _make_client()
    result = client.get_sprint_backlog(project_key="PROJ")

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]["key"] == "PROJ-1"
    assert result[0]["summary"] == "Add login feature"
    assert result[0]["issue_type"] == "Story"
    assert result[1]["key"] == "PROJ-2"
    assert result[1]["issue_type"] == "Bug"


@respx.mock
def test_get_sprint_backlog_no_active_sprint():
    """Mock 404 on active sprint endpoint; assert returns empty list (graceful degradation)."""
    # Board lookup succeeds
    respx.get(f"{JIRA_URL}/rest/agile/1.0/board").mock(
        return_value=httpx.Response(200, json={"values": [{"id": 1}]})
    )
    # Sprint lookup returns 404
    respx.get(f"{JIRA_URL}/rest/agile/1.0/board/1/sprint").mock(
        return_value=httpx.Response(404, json={"errorMessages": ["Not found"]})
    )

    client = _make_client()
    result = client.get_sprint_backlog(project_key="PROJ")

    assert result == []


@respx.mock
def test_get_issue_returns_dict():
    """Mock GET /rest/api/3/issue/{key}; assert returns dict with 'key' and 'fields'."""
    issue_key = "PROJ-10"
    respx.get(f"{JIRA_URL}/rest/api/3/issue/{issue_key}").mock(
        return_value=httpx.Response(
            200,
            json={
                "key": issue_key,
                "fields": {
                    "summary": "Test issue",
                    "description": None,
                    "issuetype": {"name": "Task"},
                },
            },
        )
    )

    client = _make_client()
    result = client.get_issue(issue_key)

    assert isinstance(result, dict)
    assert result["key"] == issue_key
    assert "fields" in result
    assert result["fields"]["summary"] == "Test issue"


@respx.mock
def test_jira_client_uses_auth_header():
    """Assert Authorization header is 'Basic base64(email:token)'."""
    issue_key = "PROJ-99"
    expected_raw = f"{EMAIL}:{TOKEN}".encode()
    expected_auth = "Basic " + base64.b64encode(expected_raw).decode()

    captured_headers = {}

    def capture_request(request: httpx.Request) -> httpx.Response:
        captured_headers["Authorization"] = request.headers.get("Authorization", "")
        return httpx.Response(
            200,
            json={"key": issue_key, "fields": {"summary": "auth check"}},
        )

    respx.get(f"{JIRA_URL}/rest/api/3/issue/{issue_key}").mock(side_effect=capture_request)

    client = _make_client(email=EMAIL)
    client.get_issue(issue_key)

    assert captured_headers.get("Authorization") == expected_auth, (
        f"Expected '{expected_auth}', got '{captured_headers.get('Authorization')}'"
    )
