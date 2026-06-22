"""Unit tests for complexity_classifier service.

Tests (6 total):
1. test_classify_small_below_threshold — component_count=1 → "small"
2. test_classify_complex_at_threshold — component_count=2 → "complex"
3. test_classify_complex_above_threshold — component_count=3 → "complex"
4. test_classify_malformed_json_defaults_to_small — bad JSON → ("small", "Classification unavailable...")
5. test_build_classify_prompt_contains_rubric_and_schema — pure unit test of prompt helper, no mock
6. test_classify_persists_to_pipeline_state_when_row_exists — verifies CLASSIFY-02 DB persistence

All LLM calls are mocked at "services.complexity_classifier.route_request".
Uses StaticPool in-memory SQLite — same pattern as test_architecture_pipeline.py.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Set env vars BEFORE any app module imports.
_TEST_KEY = Fernet.generate_key().decode()
os.environ.setdefault("ENCRYPTION_KEY", _TEST_KEY)
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# ---------------------------------------------------------------------------
# In-memory SQLite DB with StaticPool.
# ---------------------------------------------------------------------------

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

from database import Base  # noqa: E402
import models.project  # noqa: E402
import models.ticket_status  # noqa: E402
import models.pipeline_state  # noqa: E402
from models.project import Project  # noqa: E402
from models.pipeline_state import PipelineState  # noqa: E402
from services.crypto import encrypt_credential  # noqa: E402
from services.llm_router import LLMResponse  # noqa: E402
from services.complexity_classifier import (  # noqa: E402
    classify_complexity,
    _build_classify_prompt,
)

Base.metadata.create_all(TEST_ENGINE)
TestingSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def reset_tables():
    """Drop and recreate all tables before each test for full isolation."""
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)
    Base.metadata.create_all(TEST_ENGINE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db():
    return TestingSession()


def _make_llm_response(json_payload: dict) -> LLMResponse:
    return LLMResponse(provider="freellmapi", content=json.dumps(json_payload), model="auto")


def _insert_project(db) -> int:
    """Insert a minimal Project row and return its id."""
    p = Project(
        name="Test Project",
        project_key="PROJ",
        jira_url="https://jira.example.com",
        jira_token=encrypt_credential("tok"),
        confluence_url="https://conf.example.com",
        confluence_token=encrypt_credential("ctok"),
        github_token=encrypt_credential("gh-tok"),
        github_repo=encrypt_credential("acme/my-app"),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_classify_small_below_threshold():
    """component_count=1 → classification 'small'."""
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
    """component_count=2 → classification 'complex' (threshold boundary)."""
    db = _make_db()
    mock_resp = _make_llm_response(
        {"classification": "complex", "rationale": "Touches API gateway and the DB.", "component_count": 2}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp):
        complexity, rationale = classify_complexity("PROJ-2", "Add rate limiting", "Rate limit API and log to DB", db, project_id=1)

    assert complexity == "complex"
    assert rationale == "Touches API gateway and the DB."


def test_classify_complex_above_threshold():
    """component_count=3 → classification 'complex' (above threshold)."""
    db = _make_db()
    mock_resp = _make_llm_response(
        {"classification": "complex", "rationale": "Involves API, DB, and email service.", "component_count": 3}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp):
        complexity, rationale = classify_complexity("PROJ-3", "Add notifications", "Send emails on DB change via API", db, project_id=1)

    assert complexity == "complex"
    assert rationale != ""


def test_classify_malformed_json_defaults_to_small():
    """Malformed JSON from LLM → ('small', 'Classification unavailable...') without raising."""
    db = _make_db()
    bad_resp = LLMResponse(provider="freellmapi", content="NOT VALID JSON {{", model="auto")
    with patch("services.complexity_classifier.route_request", return_value=bad_resp):
        complexity, rationale = classify_complexity("PROJ-4", "Fix typo", "One-char edit", db, project_id=1)

    assert complexity == "small"
    assert "Classification unavailable" in rationale


def test_build_classify_prompt_contains_rubric_and_schema():
    """Pure unit test of _build_classify_prompt — no LLM mock required."""
    prompt = _build_classify_prompt("PROJ-99", "Enable OAuth", "Integrate Google SSO")

    assert "classification" in prompt
    assert "component_count" in prompt
    assert "rationale" in prompt
    assert "2 or more" in prompt
    assert "PROJ-99" in prompt
    assert "Enable OAuth" in prompt


def test_classify_persists_to_pipeline_state_when_row_exists():
    """CLASSIFY-02: classification and rationale are persisted to PipelineState."""
    db = _make_db()
    project_id = _insert_project(db)

    # Insert a PipelineState row for the ticket.
    row = PipelineState(
        project_id=project_id,
        ticket_key="PROJ-10",
        stage="describe",
        status="processing",
    )
    db.add(row)
    db.commit()

    mock_resp = _make_llm_response(
        {"classification": "small", "rationale": "Tiny one-liner fix.", "component_count": 1}
    )
    with patch("services.complexity_classifier.route_request", return_value=mock_resp):
        complexity, rationale = classify_complexity("PROJ-10", "Tiny fix", "One-line change", db, project_id=project_id)

    assert complexity == "small"

    saved = db.query(PipelineState).filter_by(ticket_key="PROJ-10").first()
    assert saved is not None
    assert saved.complexity == "small"
    assert saved.complexity_rationale is not None


def test_build_classify_prompt_includes_snapshot_when_provided():
    """ARCHCTX-01: codebase_snapshot content is appended to the prompt when provided."""
    prompt = _build_classify_prompt(
        "PROJ-1", "My summary", "My description",
        codebase_snapshot="# Real file: src/api.py\nSome content",
    )

    assert "src/api.py" in prompt


def test_build_classify_prompt_no_snapshot_when_none():
    """Backward compatible: no codebase_snapshot means no codebase context section."""
    prompt = _build_classify_prompt("PROJ-1", "My summary", "My description")

    assert "Codebase context" not in prompt


def test_classify_complexity_passes_snapshot_to_prompt():
    """ARCHCTX-01: classify_complexity() threads codebase_snapshot into the LLM prompt."""
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
