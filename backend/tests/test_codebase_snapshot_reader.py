"""TDD tests for codebase_snapshot_reader.get_codebase_snapshot() — SNAPSHOT-02 (Phase 19).

Tests cover:
1. Content returned when .hermes/codebase.md found (200)
2. None returned on 404 (file not yet committed)
3. None returned on network error (httpx.ConnectError)
4. None returned on non-200/non-404 (e.g. 500)
5. None returned on invalid repo slug (no HTTP call made)
6. github_token never appears in any logged message

Uses respx for httpx mocking; github_token NEVER asserted in log output (T-19-04).
"""

import base64
import logging
import os
from unittest.mock import patch

import httpx
import pytest
import respx

os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ=")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["GITHUB_API_BASE"] = "https://api.github.com"

# ---------------------------------------------------------------------------
# Module import — must happen after env vars are set
# ---------------------------------------------------------------------------

from services.codebase_snapshot_reader import get_codebase_snapshot  # noqa: E402

# ---------------------------------------------------------------------------
# Test 1: content returned when file exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_codebase_snapshot_returns_content_when_found():
    """200 response with base64 content → decoded markdown string returned."""
    raw_content = b"# Codebase Snapshot\nsome content here"
    encoded = base64.b64encode(raw_content).decode()

    respx.get("https://api.github.com/repos/owner/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(200, json={"content": encoded})
    )

    result = await get_codebase_snapshot("owner/repo", "tok")
    assert result == raw_content.decode("utf-8"), f"Expected decoded content, got {result!r}"


# ---------------------------------------------------------------------------
# Test 2: None returned on 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_codebase_snapshot_returns_none_on_404():
    """404 response (file absent) → returns None, no exception raised."""
    respx.get("https://api.github.com/repos/owner/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(404, json={"message": "Not Found"})
    )

    result = await get_codebase_snapshot("owner/repo", "tok")
    assert result is None


# ---------------------------------------------------------------------------
# Test 3: None returned on network error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_codebase_snapshot_returns_none_on_network_error():
    """httpx.ConnectError → returns None, exception does not propagate."""
    respx.get("https://api.github.com/repos/owner/repo/contents/.hermes/codebase.md").mock(
        side_effect=httpx.ConnectError("boom")
    )

    result = await get_codebase_snapshot("owner/repo", "tok")
    assert result is None


# ---------------------------------------------------------------------------
# Test 4: None returned on non-200/non-404 status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_codebase_snapshot_returns_none_on_non_200_non_404():
    """500 response → returns None, no exception propagated."""
    respx.get("https://api.github.com/repos/owner/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(500, json={"message": "Internal Server Error"})
    )

    result = await get_codebase_snapshot("owner/repo", "tok")
    assert result is None


# ---------------------------------------------------------------------------
# Test 5: None returned on invalid repo slug (no HTTP call made)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_codebase_snapshot_returns_none_on_invalid_repo_slug():
    """Invalid slug (no slash) → returns None immediately, zero HTTP calls."""
    result = await get_codebase_snapshot("not-a-valid-slug-with-no-slash", "tok")
    assert result is None
    assert len(respx.calls) == 0, f"Expected 0 HTTP calls, got {len(respx.calls)}"


# ---------------------------------------------------------------------------
# Test 6: github_token never appears in logged messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_codebase_snapshot_token_never_in_logs_or_exceptions(caplog):
    """On 500 error, the literal token string must never appear in any log message."""
    secret_token = "ghp_SECRET_TOKEN_VALUE"

    respx.get("https://api.github.com/repos/owner/repo/contents/.hermes/codebase.md").mock(
        return_value=httpx.Response(500, json={"message": "Internal Server Error"})
    )

    with caplog.at_level(logging.WARNING, logger="services.codebase_snapshot_reader"):
        result = await get_codebase_snapshot("owner/repo", secret_token)

    assert result is None

    for record in caplog.records:
        assert secret_token not in record.getMessage(), (
            f"Token leaked in log message: {record.getMessage()!r}"
        )
