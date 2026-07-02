"""Tests for the project API endpoints (MongoDB-backed).

Uses the shared mongomock fixtures in conftest.py (which sets ENCRYPTION_KEY,
points database._client at mongomock, stubs auth, and resets collections per
test). Direct DB assertions go through the repository layer / collections.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from database import get_database
from main import app
from repositories import pipeline_state_repo, projects_repo

client = TestClient(app)

TOKEN_FIELD_NAMES = {"jira_token", "github_token", "confluence_token"}

_project_counter = 0


def _unique_payload() -> dict:
    """Return a valid payload with a unique project_key to avoid unique-index clashes."""
    global _project_counter
    _project_counter += 1
    return {
        "name": f"Test Project {_project_counter}",
        "project_key": f"TESTPROJ{_project_counter}",
        "jira_url": "https://test.atlassian.net",
        "jira_email": "test@example.com",
        "jira_token": "plaintext-jira-token",
        "github_token": "plaintext-github-token",
        "confluence_url": "https://test.atlassian.net/wiki",
        "confluence_token": "plaintext-confluence-token",
        "github_repo": "acme/my-app",
    }


def test_create_project_returns_201() -> None:
    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text
    data = response.json()
    assert "id" in data
    assert isinstance(data["id"], int)


def test_create_project_response_omits_tokens() -> None:
    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text
    data = response.json()
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in response"


def test_create_project_persists_encrypted() -> None:
    payload = _unique_payload()
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    row = projects_repo.get(get_database(), project_id)
    assert row is not None
    stored_token = row.jira_token
    assert stored_token != payload["jira_token"], "Token must not be stored as plaintext"
    assert payload["jira_token"] not in stored_token
    assert stored_token.startswith("gAAAAA"), (
        f"Expected Fernet ciphertext (starts with 'gAAAAA'), got: {stored_token[:20]!r}"
    )


def test_list_projects_empty() -> None:
    """GET /api/projects on a fresh (per-test reset) DB returns 200 and []."""
    response = client.get("/api/projects")
    assert response.status_code == 200, response.text
    assert response.json() == []


def test_list_projects_after_create() -> None:
    payload = _unique_payload()
    create_resp = client.post("/api/projects", json=payload)
    assert create_resp.status_code == 201, create_resp.text

    list_resp = client.get("/api/projects")
    assert list_resp.status_code == 200, list_resp.text
    items = list_resp.json()
    assert len(items) >= 1
    assert "id" in items[0]
    assert "project_key" in items[0]


def test_get_project_by_id() -> None:
    payload = _unique_payload()
    post_response = client.post("/api/projects", json=payload)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()
    assert data["project_key"] == payload["project_key"]
    assert data["id"] == project_id


def test_get_project_by_id_omits_tokens() -> None:
    payload = _unique_payload()
    post_response = client.post("/api/projects", json=payload)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200
    data = get_response.json()
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in GET response"


def test_create_project_missing_required_field() -> None:
    payload = _unique_payload()
    del payload["project_key"]
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422, response.text


def test_create_project_includes_github_repo() -> None:
    payload = _unique_payload()
    payload["github_repo"] = "acme/my-app"
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data.get("github_repo") == "acme/my-app", (
        f"Expected decrypted 'acme/my-app', got: {data.get('github_repo')!r}"
    )


def test_create_project_github_repo_persists_encrypted() -> None:
    payload = _unique_payload()
    payload["github_repo"] = "acme/my-app"
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    row = projects_repo.get(get_database(), project_id)
    assert row is not None
    stored_repo = row.github_repo
    assert stored_repo != "acme/my-app", "github_repo must not be stored as plaintext"
    assert "acme/my-app" not in stored_repo
    assert stored_repo.startswith("gAAAAA"), (
        f"Expected Fernet ciphertext (starts with 'gAAAAA'), got: {stored_repo[:20]!r}"
    )


def test_create_project_missing_github_repo_returns_422() -> None:
    payload = _unique_payload()
    del payload["github_repo"]
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 422, response.text


def test_get_project_includes_github_repo() -> None:
    payload = _unique_payload()
    payload["github_repo"] = "acme/my-app"
    post_response = client.post("/api/projects", json=payload)
    assert post_response.status_code == 201
    project_id = post_response.json()["id"]

    get_response = client.get(f"/api/projects/{project_id}")
    assert get_response.status_code == 200, get_response.text
    data = get_response.json()
    assert data.get("github_repo") == "acme/my-app"
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data, f"Token field '{token_field}' found in GET response"


def test_create_project_with_github_repo_commits_pipeline_state() -> None:
    """POST with non-empty github_repo creates a codebase_scan PipelineState (SCAN-01)."""
    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]

    row = pipeline_state_repo.find_latest(
        get_database(), project_id=project_id, stage="codebase_scan"
    )
    assert row is not None, "PipelineState row not created for codebase_scan stage"
    assert row.status == "running"
    assert row.ticket_key == "__onboarding__"


def test_create_project_with_github_repo_schedules_scan_run(monkeypatch) -> None:
    """POST with non-empty github_repo schedules the background scan (asyncio.create_task)."""
    import asyncio as asyncio_mod

    scheduled = []

    def _fake_create_task(coro, **kwargs):
        scheduled.append(coro.cr_code.co_name)
        coro.close()  # prevent "coroutine was never awaited" warning
        return object()

    monkeypatch.setattr(asyncio_mod, "create_task", _fake_create_task)

    response = client.post("/api/projects", json=_unique_payload())
    assert response.status_code == 201, response.text

    # Two tasks are scheduled: scan + CBM index
    assert "_run_scan_background" in scheduled, f"Expected _run_scan_background in {scheduled}"
    assert "_run_cbm_index_background" in scheduled, (
        f"Expected _run_cbm_index_background in {scheduled}"
    )


# ---------------------------------------------------------------------------
# Update (PUT) and Delete (DELETE)
# ---------------------------------------------------------------------------


def test_update_project_changes_name() -> None:
    create = client.post("/api/projects", json=_unique_payload())
    assert create.status_code == 201, create.text
    project_id = create.json()["id"]

    put = client.put(f"/api/projects/{project_id}", json={"name": "Renamed Project"})
    assert put.status_code == 200, put.text
    assert put.json()["name"] == "Renamed Project"

    get = client.get(f"/api/projects/{project_id}")
    assert get.json()["name"] == "Renamed Project"


def test_update_project_omits_tokens_in_response() -> None:
    create = client.post("/api/projects", json=_unique_payload())
    project_id = create.json()["id"]
    put = client.put(f"/api/projects/{project_id}", json={"name": "X"})
    data = put.json()
    for token_field in TOKEN_FIELD_NAMES:
        assert token_field not in data


def test_update_project_reencrypts_supplied_token() -> None:
    payload = _unique_payload()
    create = client.post("/api/projects", json=payload)
    project_id = create.json()["id"]

    before = projects_repo.get(get_database(), project_id).jira_token

    put = client.put(f"/api/projects/{project_id}", json={"jira_token": "new-secret"})
    assert put.status_code == 200, put.text

    row = projects_repo.get(get_database(), project_id)
    assert row.jira_token != before, "jira_token should change when supplied"
    assert row.jira_token.startswith("gAAAAA"), "must be Fernet ciphertext"
    assert "new-secret" not in row.jira_token, "must not store plaintext"
    # github_token was not supplied — must be untouched ciphertext
    assert row.github_token.startswith("gAAAAA")


def test_update_project_not_found_returns_404() -> None:
    resp = client.put("/api/projects/999999", json={"name": "Nope"})
    assert resp.status_code == 404, resp.text


def test_update_project_duplicate_key_returns_409() -> None:
    first = client.post("/api/projects", json=_unique_payload())
    first_key = first.json()["project_key"]
    second = client.post("/api/projects", json=_unique_payload())
    second_id = second.json()["id"]

    resp = client.put(f"/api/projects/{second_id}", json={"project_key": first_key})
    assert resp.status_code == 409, resp.text


def test_delete_project_returns_204_then_404() -> None:
    create = client.post("/api/projects", json=_unique_payload())
    project_id = create.json()["id"]

    delete = client.delete(f"/api/projects/{project_id}")
    assert delete.status_code == 204, delete.text

    get = client.get(f"/api/projects/{project_id}")
    assert get.status_code == 404


def test_delete_project_not_found_returns_404() -> None:
    resp = client.delete("/api/projects/999999")
    assert resp.status_code == 404, resp.text


def test_delete_project_removes_pipeline_states() -> None:
    """DELETE also clears the project's pipeline_states (no orphan rows)."""
    create = client.post("/api/projects", json=_unique_payload())
    project_id = create.json()["id"]  # onboarding scan creates a PipelineState row

    client.delete(f"/api/projects/{project_id}")

    remaining = get_database()["pipeline_states"].count_documents({"project_id": project_id})
    assert remaining == 0, "pipeline_states should be removed with the project"


def test_delete_project_removes_agent_events() -> None:
    """DELETE also clears the project's agent_events (no orphan rows)."""
    from repositories import agent_event_repo

    create = client.post("/api/projects", json=_unique_payload())
    project_id = create.json()["id"]
    db = get_database()
    agent_event_repo.append(db, project_id, "P-1", "dev", "thinking", "pondering")

    client.delete(f"/api/projects/{project_id}")

    remaining = db["agent_events"].count_documents({"project_id": project_id})
    assert remaining == 0, "agent_events should be removed with the project"


def test_create_project_schedules_cbm_index() -> None:
    """CTX-01: cbm_call("index_repository", ...) is scheduled when github_repo is set."""
    mock_cloned = MagicMock()
    mock_cloned.workspace_path = "/tmp/fake-clone"
    mock_cloned.owner = "acme"
    mock_cloned.repo = "my-app"

    with (
        patch("routers.projects.codebase_scan_service.run", new_callable=AsyncMock),
        patch("routers.projects.repo_clone.clone_repository", return_value=mock_cloned),
        patch("routers.projects.cbm_call", return_value={"status": "indexed"}) as mock_cbm,
        patch("routers.projects.shutil.rmtree"),
        patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread,
    ):
        response = client.post("/api/projects", json=_unique_payload())
        assert response.status_code == 201, response.text
        # asyncio.to_thread wraps the synchronous cbm_call
        mock_to_thread.assert_called()
        # Workspace cleanup happens regardless (rmtree mock prevents FS side-effects)


def test_create_project_cbm_index_graceful_on_clone_failure() -> None:
    """CTX-01: if clone fails, project creation still returns 201."""
    with (
        patch("routers.projects.codebase_scan_service.run", new_callable=AsyncMock),
        patch(
            "routers.projects.repo_clone.clone_repository",
            side_effect=RuntimeError("git clone failed"),
        ),
    ):
        response = client.post("/api/projects", json=_unique_payload())
        assert response.status_code == 201, response.text
