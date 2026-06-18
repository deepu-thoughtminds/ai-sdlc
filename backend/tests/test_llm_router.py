"""Tests for llm_router.route_request() routing logic.

TDD RED phase: These tests specify routing behaviour (heavy vs light) and
verify the HEAVY_STAGES constant. httpx.post is mocked to prevent real
network calls during testing.
"""

import pytest
from unittest.mock import MagicMock, patch

from services.llm_router import HEAVY_STAGES, LLMResponse, route_request


def _make_httpx_mock(content="test response", model="deepseek-coder"):
    """Helper: create a mock httpx response matching OpenAI-compatible shape."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "model": model,
    }
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def test_architecture_stage_routes_to_freellmapi():
    """Test 1: route_request('architecture', ...) -> provider='freellmapi'."""
    with patch("httpx.post", return_value=_make_httpx_mock()) as mock_post:
        result = route_request("architecture", "design a system")
    assert isinstance(result, LLMResponse)
    assert result.provider == "freellmapi"
    mock_post.assert_called_once()


def test_codegen_stage_routes_to_freellmapi():
    """Test 2: route_request('codegen', ...) -> provider='freellmapi'."""
    with patch("httpx.post", return_value=_make_httpx_mock()) as mock_post:
        result = route_request("codegen", "write a function")
    assert result.provider == "freellmapi"
    mock_post.assert_called_once()


def test_testgen_stage_routes_to_freellmapi():
    """Test 3: route_request('testgen', ...) -> provider='freellmapi'."""
    with patch("httpx.post", return_value=_make_httpx_mock()) as mock_post:
        result = route_request("testgen", "write tests for this")
    assert result.provider == "freellmapi"
    mock_post.assert_called_once()


def test_describe_stage_routes_to_main_model():
    """Test 4: route_request('describe', ...) -> provider='main_model', no httpx call."""
    with patch("httpx.post") as mock_post:
        result = route_request("describe", "describe this feature")
    assert result.provider == "main_model"
    mock_post.assert_not_called()


def test_assign_stage_routes_to_main_model():
    """Test 5: route_request('assign', ...) -> provider='main_model', no httpx call."""
    with patch("httpx.post") as mock_post:
        result = route_request("assign", "assign to alice")
    assert result.provider == "main_model"
    mock_post.assert_not_called()


def test_heavy_stages_constant_contains_expected_stages():
    """Verify HEAVY_STAGES contains architecture, codegen, testgen."""
    assert "architecture" in HEAVY_STAGES
    assert "codegen" in HEAVY_STAGES
    assert "testgen" in HEAVY_STAGES
