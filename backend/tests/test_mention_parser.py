"""Tests mention_parser.parse_mention().

All classify_intent calls are mocked — no live API keys required.
"""

import pytest
from unittest.mock import patch, MagicMock

from services.mention_parser import MentionResult, parse_mention
from services.intent_router import IntentResult


def _intent(action: str, confidence: float = 0.9, entities: dict | None = None) -> IntentResult:
    return IntentResult(action=action, confidence=confidence, entities=entities or {})


# ---------------------------------------------------------------------------
# parse_mention tests
# ---------------------------------------------------------------------------


def test_hermes_describe_returns_mention_result():
    """@jarvis describe -> MentionResult(action='describe') via LLM."""
    with patch("services.mention_parser.classify_intent", return_value=_intent("describe")):
        result = parse_mention("@jarvis describe")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.action == "describe"


def test_hermes_architecture_returns_mention_result():
    """@jarvis architecture -> MentionResult(action='architecture')."""
    with patch("services.mention_parser.classify_intent", return_value=_intent("architecture")):
        result = parse_mention("@jarvis architecture")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.action == "architecture"


def test_no_mention_returns_none():
    """Plain text with no @jarvis mention -> None (classify_intent not called)."""
    with patch("services.mention_parser.classify_intent") as mock_classify:
        result = parse_mention("Hey team, what do you think?")
    assert result is None
    mock_classify.assert_not_called()


def test_hermes_assign_with_extra_token():
    """@jarvis assign @alice -> MentionResult(action='assign', extra='@alice')."""
    with patch("services.mention_parser.classify_intent", return_value=_intent("assign", entities={"user": "@alice"})):
        result = parse_mention("@jarvis assign @alice")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.action == "assign"
    assert result.extra == "@alice"


def test_unrecognized_intent_returns_none():
    """@jarvis unknown-command -> None (LLM returns None)."""
    with patch("services.mention_parser.classify_intent", return_value=None):
        result = parse_mention("@jarvis unknown-command")
    assert result is None


def test_approve_story_description_returns_mention_result():
    """@jarvis approve story description -> MentionResult(action='approve')."""
    with patch("services.mention_parser.classify_intent", return_value=_intent("approve", entities={"target": "story description"})):
        result = parse_mention("@jarvis approve story description")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.action == "approve"
    assert result.extra.lower().strip() == "story description"


def test_approve_architecture_returns_mention_result():
    """@jarvis approve architecture -> MentionResult(action='approve')."""
    with patch("services.mention_parser.classify_intent", return_value=_intent("approve", entities={"target": "architecture"})):
        result = parse_mention("@jarvis approve architecture")
    assert result is not None
    assert result.action == "approve"
    assert result.extra.lower().strip() == "architecture"


def test_approve_unknown_subcmd_via_llm_fallback():
    """@jarvis approve something-else -> None (LLM doesn't recognize it)."""
    with patch("services.mention_parser.classify_intent", return_value=None):
        result = parse_mention("@jarvis approve something-else")
    assert result is None


def test_start_coding_returns_mention_result():
    """@jarvis start coding -> MentionResult(action='start_coding')."""
    with patch("services.mention_parser.classify_intent", return_value=_intent("start_coding")):
        result = parse_mention("@jarvis start coding")
    assert result is not None
    assert result.action == "start_coding"


def test_merge_pr_returns_mention_result():
    """@jarvis merge pr -> MentionResult(action='merge_pr')."""
    with patch("services.mention_parser.classify_intent", return_value=_intent("merge_pr")):
        result = parse_mention("@jarvis merge pr")
    assert result is not None
    assert result.action == "merge_pr"
