"""Tests for architecture_pipeline.run() — single-pass complexity-aware pipeline.

Phase 34: route_request → _run_opencode_arch, get_codebase_snapshot → _query_arch_context.

Tests (7 total):
1. test_run_complex_path — classify_complexity returns "complex"; generate_diagram called;
   publish_architecture called with is_complex=True; result contains "Multi-component feature"
2. test_run_simple_path — classify_complexity returns "small"; generate_diagram NOT called;
   publish_architecture called with is_complex=False; result contains "Simple change"
3. test_run_draft_content_is_human_readable — PipelineState.draft_content is a plain string,
   not JSON, does not start with "{"
4. test_run_creates_pipeline_state_complete — PipelineState status="complete" after run()
5. test_run_graceful_on_confluence_failure — Confluence raises; pipeline still returns string;
   no "https://conf" in result
6. test_run_calls_opencode_with_summary — _run_opencode_arch called and issue_summary in prompt
7. test_run_posts_jira_comment — hermes_post_comment is called with the architecture comment body

Uses mongomock in-memory DB; unittest.mock.patch for LLM, classify_complexity, drawio,
Confluence, and hermes_post_comment dependencies.

Threat T-04-01: prompt must not contain token values — verified in test 6.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from database import get_database
from repositories import pipeline_state_repo
from services.crypto import encrypt_credential

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Stub LLM return value: _run_opencode_arch returns (content, reasoning) tuple.
_COMPLEX_CONTENT = (
    "## Summary\n"
    "This is a complex multi-service architecture.\n"
    "## Approach\n"
    "Use microservices with async messaging.\n"
    "## Component Breakdown\n"
    "API Gateway, Auth Service, User Service\n"
    "## Integration Points\n"
    "REST between gateway and services; Kafka for events\n"
    "## Key Decisions\n"
    "Use event sourcing for audit trail\n"
    "## Risks\n"
    "High coupling between services if not decoupled properly"
)

_SIMPLE_CONTENT = (
    "## Summary\n"
    "Simple single-service change.\n"
    "## Approach\n"
    "Add a field to the existing User model.\n"
    "## Key Decisions\n"
    "Minimal change — no new services needed\n"
    "## Risks\n"
    "Low risk; backward compatible"
)

_GRAPH_CONTEXT = "- architecture_pipeline (backend/services/architecture_pipeline.py)"


def _make_mock_project():
    """Return a mock Project with all fields needed by architecture_pipeline.run()."""
    p = MagicMock()
    p.id = 1
    p.project_key = "PROJ"
    p.jira_url = "https://jira.example.com"
    p.jira_token = encrypt_credential("jira-secret-token")
    p.confluence_url = "https://confluence.example.com"
    p.confluence_token = encrypt_credential("conf-secret-token")
    p.github_repo = encrypt_credential("acme/my-app")
    p.github_token = encrypt_credential("ghp-test-token")
    return p


def _make_db():
    """Return the shared mongomock Database handle."""
    return get_database()


def _arch_patches(
    *,
    complexity=("small", "single service"),
    graph_context=_GRAPH_CONTEXT,
    opencode_content=_SIMPLE_CONTENT,
    confluence_return="https://conf.example.com/wiki/spaces/PROJ/pages/1",
    confluence_side_effect=None,
):
    """Return a list of patch() context managers for common architecture pipeline deps."""
    publish_kwargs = {"new_callable": AsyncMock}
    if confluence_side_effect is not None:
        publish_kwargs["side_effect"] = confluence_side_effect
    else:
        publish_kwargs["return_value"] = confluence_return

    return [
        patch(
            "services.architecture_pipeline.classify_complexity",
            return_value=complexity,
        ),
        patch(
            "services.architecture_pipeline._query_arch_context",
            new_callable=AsyncMock,
            return_value=graph_context,
        ),
        patch(
            "services.architecture_pipeline._run_opencode_arch",
            new_callable=AsyncMock,
            return_value=(opencode_content, ""),
        ),
        patch(
            "services.architecture_pipeline.generate_diagram",
            return_value="<mxGraphModel/>",
        ),
        patch(
            "services.architecture_pipeline.generate_viewer_url",
            return_value="https://diagrams.net/view",
        ),
        patch(
            "services.architecture_pipeline.publish_architecture",
            **publish_kwargs,
        ),
        patch(
            "services.architecture_pipeline.hermes_post_comment",
            new_callable=AsyncMock,
            return_value={},
        ),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_complex_path():
    """classify_complexity returns 'complex': generate_diagram called once,
    publish_architecture called with is_complex=True, result contains
    'Multi-component feature — diagram included'.
    """
    db = _make_db()
    patches = _arch_patches(
        complexity=("complex", "touches 3 services"),
        opencode_content=_COMPLEX_CONTENT,
    )
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as mock_generate_diagram,
        patches[4],
        patches[5] as mock_publish,
        patches[6],
    ):
        from services.architecture_pipeline import run

        result = await run(
            _make_mock_project(), "PROJ-1", "Auth feature", "User can login", db
        )

    assert isinstance(result, str)
    assert "Multi-component feature — diagram included" in result
    mock_generate_diagram.assert_called_once()
    call_kwargs = mock_publish.call_args[1] if mock_publish.call_args[1] else {}
    call_args = mock_publish.call_args[0] if mock_publish.call_args[0] else ()
    assert call_kwargs.get("is_complex") is True or (
        len(call_args) > 6 and call_args[6] is True
    )


@pytest.mark.asyncio
async def test_run_simple_path():
    """classify_complexity returns 'small': generate_diagram NOT called,
    publish_architecture called with is_complex=False, result contains
    'Simple change — text architecture'.
    """
    db = _make_db()
    patches = _arch_patches(
        complexity=("small", "single service change"),
        opencode_content=_SIMPLE_CONTENT,
    )
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3] as mock_generate_diagram,
        patches[4],
        patches[5] as mock_publish,
        patches[6],
    ):
        from services.architecture_pipeline import run

        result = await run(
            _make_mock_project(), "PROJ-1", "Add field", "Add email field to User", db
        )

    assert isinstance(result, str)
    assert "Simple change — text architecture" in result
    mock_generate_diagram.assert_not_called()
    call_kwargs = mock_publish.call_args[1] if mock_publish.call_args[1] else {}
    call_args = mock_publish.call_args[0] if mock_publish.call_args[0] else ()
    assert call_kwargs.get("is_complex") is False or (
        len(call_args) > 6 and call_args[6] is False
    )


@pytest.mark.asyncio
async def test_run_draft_content_is_human_readable():
    """After run(), PipelineState.draft_content is a plain string — not JSON,
    does not start with '{'.
    """
    db = _make_db()
    patches = _arch_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        from services.architecture_pipeline import run

        await run(_make_mock_project(), "PROJ-1", "Simple fix", "Fix null pointer", db)

    row = pipeline_state_repo.find_latest(
        db, ticket_key="PROJ-1", stage="architecture"
    )
    assert row is not None
    assert row.draft_content is not None
    content = row.draft_content
    assert not content.strip().startswith("{"), "draft_content must not be JSON"
    try:
        json.loads(content)
        raise AssertionError("draft_content must not be valid JSON")
    except (json.JSONDecodeError, ValueError):
        pass  # expected — content is plain text


@pytest.mark.asyncio
async def test_run_creates_pipeline_state_complete():
    """After run() completes, PipelineState has stage='architecture'
    and status='complete'.
    """
    db = _make_db()
    patches = _arch_patches(
        complexity=("complex", "multi-service"),
        opencode_content=_COMPLEX_CONTENT,
    )
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        from services.architecture_pipeline import run

        await run(_make_mock_project(), "PROJ-1", "Big feature", "Needs many services", db)

    row = pipeline_state_repo.find_latest(
        db, ticket_key="PROJ-1", stage="architecture"
    )
    assert row is not None
    assert row.status == "complete", f"Expected 'complete', got '{row.status}'"


@pytest.mark.asyncio
async def test_run_graceful_on_confluence_failure():
    """When Confluence publish raises an exception, run() still returns non-empty string
    and 'https://conf' is not in the result (graceful degradation — T-04-03).
    """
    db = _make_db()
    patches = _arch_patches(
        complexity=("complex", "multi-service"),
        opencode_content=_COMPLEX_CONTENT,
        confluence_side_effect=Exception("network error"),
    )
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        from services.architecture_pipeline import run

        result = await run(
            _make_mock_project(), "PROJ-1", "Big feature", "Needs services", db
        )

    assert isinstance(result, str)
    assert len(result) > 0, "run() must return non-empty string even on Confluence failure"
    assert "https://conf" not in result, "Confluence URL must not appear when publishing failed"


@pytest.mark.asyncio
async def test_run_calls_opencode_with_summary():
    """_run_opencode_arch is called and issue_summary appears in the prompt.

    Also verifies T-04-01: prompt must not contain decrypted token values.
    """
    db = _make_db()
    patches = _arch_patches()
    with (
        patches[0],
        patches[1],
        patches[2] as mock_opencode,
        patches[3],
        patches[4],
        patches[5],
        patches[6],
    ):
        from services.architecture_pipeline import run

        await run(
            _make_mock_project(), "PROJ-1", "Auth feature", "User can login", db
        )

    assert mock_opencode.called, "_run_opencode_arch must be called"
    prompt = mock_opencode.call_args[0][0]
    assert "Auth feature" in prompt, "issue_summary must appear in prompt"
    # T-04-01: prompt must NOT contain token values
    assert "jira-secret-token" not in prompt
    assert "conf-secret-token" not in prompt


@pytest.mark.asyncio
async def test_run_posts_jira_comment():
    """hermes_post_comment is called once with the architecture comment body.

    Verifies CR-01: run() must actually post the result to Jira.
    The 5th positional arg (body) must contain the issue key.
    """
    db = _make_db()
    patches = _arch_patches()
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patches[6] as mock_post,
    ):
        from services.architecture_pipeline import run
        await run(_make_mock_project(), "PROJ-1", "Fix", "Small fix", db)

    mock_post.assert_called_once()
    call_body = mock_post.call_args[0][4]  # 5th positional arg is the comment body
    assert "PROJ-1" in call_body, "comment body must reference the issue key"
