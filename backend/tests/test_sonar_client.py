"""Unit tests for services.sonar_client — SONAR-02, SONAR-03.

All tests mock httpx.get / httpx.post — no network, no Docker, no real sleep.

Readiness tests (4):
  test_wait_returns_on_up              — returns immediately on UP
  test_wait_retries_on_starting        — retries until UP
  test_wait_raises_on_timeout          — raises SonarQubeNotReadyError on timeout
  test_wait_swallows_request_error     — swallows RequestError, returns on next UP

Token bootstrap tests (3):
  test_bootstrap_returns_env_token_if_set     — no HTTP calls when SONAR_TOKEN set
  test_bootstrap_generates_token_when_absent  — generates token and sets env
  test_bootstrap_revokes_and_regenerates_existing — revokes existing, generates new
"""

from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from services.sonar_client import (
    SonarQubeNotReadyError,
    bootstrap_token,
    ensure_sonarqube_ready,
    wait_until_ready,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a minimal httpx.Response mock."""
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    m.raise_for_status.return_value = None
    return m


# ---------------------------------------------------------------------------
# SONAR-02 — Readiness polling (wait_until_ready)
# ---------------------------------------------------------------------------

class TestWaitUntilReady:
    def test_wait_returns_on_up(self, monkeypatch):
        """Returns immediately when the first poll returns status=UP."""
        monkeypatch.delenv("SONAR_READY_TIMEOUT", raising=False)
        with patch("httpx.get", return_value=_mock_response(json_data={"status": "UP"})) as mock_get:
            wait_until_ready("http://localhost:9000", timeout_secs=10)
        mock_get.assert_called_once()

    def test_wait_retries_on_starting(self, monkeypatch):
        """Retries when status=STARTING, then returns on UP."""
        monkeypatch.delenv("SONAR_READY_TIMEOUT", raising=False)
        responses = [
            _mock_response(json_data={"status": "STARTING"}),
            _mock_response(json_data={"status": "UP"}),
        ]
        with patch("httpx.get", side_effect=responses) as mock_get, \
             patch("time.sleep"):  # speed up test
            wait_until_ready("http://localhost:9000", timeout_secs=30)
        assert mock_get.call_count == 2

    def test_wait_raises_on_timeout(self, monkeypatch):
        """Raises SonarQubeNotReadyError when status never reaches UP."""
        monkeypatch.delenv("SONAR_READY_TIMEOUT", raising=False)
        # Patch monotonic: 0.0 (deadline set), 0.0 (first loop check), 200.0 (past deadline)
        _times = iter([0.0, 0.0, 200.0])
        with patch("services.sonar_client.time.monotonic", side_effect=_times), \
             patch("httpx.get", return_value=_mock_response(json_data={"status": "STARTING"})), \
             patch("time.sleep"):
            with pytest.raises(SonarQubeNotReadyError, match="did not reach UP"):
                wait_until_ready("http://localhost:9000", timeout_secs=10)

    def test_wait_swallows_request_error(self, monkeypatch):
        """Swallows httpx.RequestError on first call, returns on next UP response."""
        monkeypatch.delenv("SONAR_READY_TIMEOUT", raising=False)
        responses = [
            httpx.RequestError("connection refused"),
            _mock_response(json_data={"status": "UP"}),
        ]
        with patch("httpx.get", side_effect=responses) as mock_get, \
             patch("time.sleep"):
            wait_until_ready("http://localhost:9000", timeout_secs=30)
        assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# SONAR-03 — Token bootstrap (bootstrap_token)
# ---------------------------------------------------------------------------

class TestBootstrapToken:
    def test_bootstrap_returns_env_token_if_set(self, monkeypatch):
        """Returns existing SONAR_TOKEN from env; makes zero HTTP calls."""
        monkeypatch.setenv("SONAR_TOKEN", "existing-tok")
        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            result = bootstrap_token("http://localhost:9000")
        assert result == "existing-tok"
        assert mock_get.call_count == 0
        assert mock_post.call_count == 0

    def test_bootstrap_generates_token_when_absent(self, monkeypatch):
        """Generates a new token and stores it in os.environ when none exists."""
        monkeypatch.delenv("SONAR_TOKEN", raising=False)
        # GET /api/user_tokens/search → no existing tokens
        search_resp = _mock_response(json_data={"userTokens": []})
        # POST /api/user_tokens/generate → returns new token
        generate_resp = _mock_response(json_data={"token": "new-tok-123"})

        with patch("httpx.get", return_value=search_resp), \
             patch("httpx.post", return_value=generate_resp) as mock_post:
            result = bootstrap_token("http://localhost:9000", admin_password="admin")

        assert result == "new-tok-123"
        import os
        assert os.environ.get("SONAR_TOKEN") == "new-tok-123"
        # Only one POST (generate), no revoke
        assert mock_post.call_count == 1

    def test_bootstrap_revokes_and_regenerates_existing(self, monkeypatch):
        """Revokes existing 'jarvis-scanner' token then generates a new one."""
        monkeypatch.delenv("SONAR_TOKEN", raising=False)
        # GET /api/user_tokens/search → existing token found
        search_resp = _mock_response(json_data={"userTokens": [{"name": "jarvis-scanner"}]})
        # POST /api/user_tokens/revoke → 200 no body
        revoke_resp = _mock_response(json_data={})
        # POST /api/user_tokens/generate → new token
        generate_resp = _mock_response(json_data={"token": "regen-tok"})

        post_responses = [revoke_resp, generate_resp]
        with patch("httpx.get", return_value=search_resp), \
             patch("httpx.post", side_effect=post_responses) as mock_post:
            result = bootstrap_token("http://localhost:9000", admin_password="admin")

        assert result == "regen-tok"
        import os
        assert os.environ.get("SONAR_TOKEN") == "regen-tok"
        # Two POSTs: revoke + generate
        assert mock_post.call_count == 2
