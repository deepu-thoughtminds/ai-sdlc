"""Unit tests for services.intent_router.classify_intent().

All LLM calls are mocked — no live API keys required.
"""

import json
from unittest.mock import patch

import pytest

from services.intent_router import IntentResult, VALID_ACTIONS, classify_intent
from services.llm_router import LLMResponse


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(provider="freellmapi", content=content, model="auto")


def _json(action: str, confidence: float, entities: dict | None = None) -> str:
    return json.dumps({"action": action, "confidence": confidence, "entities": entities or {}})


# ---------------------------------------------------------------------------
# classify_intent tests
# ---------------------------------------------------------------------------


def test_classify_start_coding():
    with patch("services.intent_router.route_request", return_value=_make_llm_response(_json("start_coding", 0.9))):
        result = classify_intent("start coding")
    assert result is not None
    assert result.action == "start_coding"
    assert result.confidence == pytest.approx(0.9)
    assert result.entities == {}


def test_classify_merge_pr():
    with patch("services.intent_router.route_request", return_value=_make_llm_response(_json("merge_pr", 0.85))):
        result = classify_intent("merge pr")
    assert result is not None
    assert result.action == "merge_pr"


def test_classify_assign_with_entity():
    with patch("services.intent_router.route_request", return_value=_make_llm_response(_json("assign", 0.9, {"user": "@alice"}))):
        result = classify_intent("assign @alice")
    assert result is not None
    assert result.action == "assign"
    assert result.entities == {"user": "@alice"}


def test_classify_unknown_action():
    with patch("services.intent_router.route_request", return_value=_make_llm_response(_json("unknown", 0.0))):
        result = classify_intent("do something weird")
    assert result is None


def test_classify_low_confidence():
    with patch("services.intent_router.route_request", return_value=_make_llm_response(_json("architecture", 0.3))):
        result = classify_intent("arch")
    assert result is None


def test_classify_malformed_json():
    with patch("services.intent_router.route_request", return_value=_make_llm_response("definitely not json")):
        result = classify_intent("some command")
    assert result is None


def test_classify_llm_raises():
    with patch("services.intent_router.route_request", side_effect=Exception("network error")):
        result = classify_intent("some command")
    assert result is None


def test_valid_actions_set():
    assert VALID_ACTIONS == {"describe", "architecture", "start_coding", "merge_pr", "assign", "approve"}


def test_classify_architecture():
    with patch("services.intent_router.route_request", return_value=_make_llm_response(_json("architecture", 0.95))):
        result = classify_intent("architecture")
    assert result is not None
    assert result.action == "architecture"


def test_classify_approve_with_target():
    with patch("services.intent_router.route_request", return_value=_make_llm_response(_json("approve", 0.9, {"target": "story description"}))):
        result = classify_intent("approve story description")
    assert result is not None
    assert result.action == "approve"
    assert result.entities.get("target") == "story description"


def test_classify_markdown_fenced_json():
    """LLMs sometimes wrap JSON in markdown code fences — should still parse."""
    content = "```json\n" + _json("describe", 0.88) + "\n```"
    with patch("services.intent_router.route_request", return_value=_make_llm_response(content)):
        result = classify_intent("describe")
    assert result is not None
    assert result.action == "describe"
