"""Unit tests for complexity_classifier service.

All LLM calls are mocked at "services.complexity_classifier.route_request".
Uses the shared mongomock fixtures in conftest.py. The classifier itself does
no DB writes (WR-04) — the DB is only used by the persistence-isolation test.
"""

import json
from unittest.mock import patch

from database import get_database
from repositories import pipeline_state_repo
from services.crypto import encrypt_credential
from services.llm_router import LLMResponse
from services.complexity_classifier import classify_complexity, _build_classify_prompt
from tests.support import make_project


def _make_db():
    return get_database()


def _make_llm_response(json_payload: dict) -> LLMResponse:
    return LLMResponse(provider="freellmapi", content=json.dumps(json_payload), model="auto")


def _insert_project(db) -> int:
    """Insert a minimal project and return its id."""
    return make_project(
        db,
        project_key="PROJ",
        jira_token=encrypt_credential("tok"),
        confluence_token=encrypt_credential("ctok"),
        github_token=encrypt_credential("gh-tok"),
        github_repo=encrypt_credential("acme/my-app"),
    ).id


def test_classify_small_below_threshold():
    db = _make_db()
    mock_resp = _make_llm_response(
        {"classification": "small", "rationale": "Only one component — the auth service.", "component_count": 1}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp) as mock_rr:
        complexity, rationale = classify_complexity("PROJ-1", "Add logout button", "Removes the logout endpoint", db, project_id=1)

    assert complexity == "small"
    assert rationale == "Only one component — the auth service."
    mock_rr.assert_called_once()


def test_classify_complex_at_threshold():
    db = _make_db()
    mock_resp = _make_llm_response(
        {"classification": "complex", "rationale": "Touches API gateway and the DB.", "component_count": 2}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp):
        complexity, rationale = classify_complexity("PROJ-2", "Add rate limiting", "Rate limit API and log to DB", db, project_id=1)

    assert complexity == "complex"
    assert rationale == "Touches API gateway and the DB."


def test_classify_complex_above_threshold():
    db = _make_db()
    mock_resp = _make_llm_response(
        {"classification": "complex", "rationale": "Involves API, DB, and email service.", "component_count": 3}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp):
        complexity, rationale = classify_complexity("PROJ-3", "Add notifications", "Send emails on DB change via API", db, project_id=1)

    assert complexity == "complex"
    assert rationale != ""


def test_classify_malformed_json_defaults_to_small():
    db = _make_db()
    bad_resp = LLMResponse(provider="freellmapi", content="NOT VALID JSON {{", model="auto")
    with patch("services.complexity_classifier.route_request", return_value=bad_resp):
        complexity, rationale = classify_complexity("PROJ-4", "Fix typo", "One-char edit", db, project_id=1)

    assert complexity == "small"
    assert "Classification unavailable" in rationale


def test_build_classify_prompt_contains_rubric_and_schema():
    prompt = _build_classify_prompt("PROJ-99", "Enable OAuth", "Integrate Google SSO")

    assert "classification" in prompt
    assert "component_count" in prompt
    assert "rationale" in prompt
    assert "2 or more" in prompt
    assert "PROJ-99" in prompt
    assert "Enable OAuth" in prompt


def test_classify_does_not_write_to_pipeline_state():
    """WR-04: classify_complexity() no longer writes to DB — caller persists complexity."""
    db = _make_db()
    project_id = _insert_project(db)

    row = pipeline_state_repo.create(
        db, project_id, "PROJ-10", "describe", status="processing"
    )

    mock_resp = _make_llm_response(
        {"classification": "small", "rationale": "Tiny one-liner fix.", "component_count": 1}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp):
        complexity, rationale = classify_complexity("PROJ-10", "Tiny fix", "One-line change", db, project_id=project_id)

    assert complexity == "small"
    assert rationale == "Tiny one-liner fix."

    # Verify the classifier did NOT write to PipelineState — the caller owns that.
    saved = pipeline_state_repo.get(db, row.id)
    assert saved is not None
    assert saved.complexity is None
    assert saved.complexity_rationale is None


def test_build_classify_prompt_includes_snapshot_when_provided():
    prompt = _build_classify_prompt(
        "PROJ-1", "My summary", "My description",
        codebase_snapshot="# Real file: src/api.py\nSome content",
    )

    assert "src/api.py" in prompt


def test_build_classify_prompt_no_snapshot_when_none():
    prompt = _build_classify_prompt("PROJ-1", "My summary", "My description")

    assert "Codebase context" not in prompt


def test_classify_complexity_passes_snapshot_to_prompt():
    db = _make_db()
    mock_resp = _make_llm_response(
        {"classification": "small", "rationale": "one comp", "component_count": 1}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp) as mock_rr:
        classify_complexity(
            "PROJ-1", "summary", "desc", db, project_id=1,
            codebase_snapshot="# src/unique_module.py content",
        )

    mock_rr.assert_called_once()
    prompt = mock_rr.call_args[0][1]
    assert "unique_module.py" in prompt
