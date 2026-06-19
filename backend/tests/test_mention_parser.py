"""Tests for mention_parser.parse_mention().

TDD RED phase: These tests are written to specify the exact behaviour of
parse_mention before verifying the implementation is complete and correct.
Pure unit tests — no HTTP, no mocking needed.
"""

import pytest
from services.mention_parser import MentionResult, parse_mention


def test_hermes_describe_returns_mention_result():
    """Test 1: @jarvis describe -> MentionResult(mention_target='jarvis', stage='describe')."""
    result = parse_mention("@jarvis describe")
    assert result is not None
    assert isinstance(result, MentionResult)
    assert result.mention_target == "jarvis"
    assert result.stage == "describe"


def test_hermes_architecture_returns_mention_result():
    """Test 2: @jarvis architecture -> MentionResult(mention_target='jarvis', stage='architecture')."""
    result = parse_mention("@jarvis architecture")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.stage == "architecture"


def test_no_mention_returns_none():
    """Test 3: Plain text with no @jarvis mention -> None."""
    result = parse_mention("Hey team, what do you think?")
    assert result is None


def test_hermes_assign_with_extra_token():
    """Test 4: @jarvis assign @alice -> MentionResult with extra='@alice'."""
    result = parse_mention("@jarvis assign @alice")
    assert result is not None
    assert result.mention_target == "jarvis"
    assert result.stage == "assign"
    assert result.extra == "@alice"


def test_unknown_stage_returns_none():
    """Test 5: @jarvis unknown-command -> None (unrecognised stage silently ignored)."""
    result = parse_mention("@jarvis unknown-command")
    assert result is None
