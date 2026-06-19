"""Tests for mention_parser.parse_mention().

Pure unit tests — no HTTP, no mocking needed.
"""

import pytest
from services.mention_parser import MentionResult, parse_mention


def test_hermes_describe_returns_none():
    """@jarvis describe -> None (removed; auto-trigger on Story creation is primary)."""
    result = parse_mention("@jarvis describe")
    assert result is None


def test_hermes_architecture_returns_mention_result():
    """@jarvis architecture -> MentionResult(stage='architecture')."""
    result = parse_mention("@jarvis architecture")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.stage == "architecture"


def test_no_mention_returns_none():
    """Plain text with no @jarvis mention -> None."""
    result = parse_mention("Hey team, what do you think?")
    assert result is None


def test_hermes_assign_with_extra_token():
    """@jarvis assign @alice -> MentionResult with extra='@alice'."""
    result = parse_mention("@jarvis assign @alice")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.stage == "assign"
    assert result.extra == "@alice"


def test_unknown_stage_returns_none():
    """@jarvis unknown-command -> None (unrecognised stage silently ignored)."""
    result = parse_mention("@jarvis unknown-command")
    assert result is None


def test_approve_story_description_returns_mention_result():
    """@jarvis approve story description -> MentionResult(stage='approve', extra='story description')."""
    result = parse_mention("@jarvis approve story description")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.stage == "approve"
    assert result.extra.lower().strip() == "story description"


def test_approve_architecture_returns_mention_result():
    """@jarvis approve architecture -> MentionResult(stage='approve', extra='architecture')."""
    result = parse_mention("@jarvis approve architecture")
    assert result is not None
    assert result.stage == "approve"
    assert result.extra.lower().strip() == "architecture"


def test_approve_unknown_subcmd_returns_none():
    """@jarvis approve something-else -> None (T-o0v-03: unknown sub-command rejected)."""
    result = parse_mention("@jarvis approve something-else")
    assert result is None
