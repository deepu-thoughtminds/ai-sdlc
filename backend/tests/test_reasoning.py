"""Tests for services/reasoning.py — the <thinking> split + chunking helpers."""

from services.reasoning import (
    MAX_THINKING_CHARS,
    REASONING_INSTRUCTION,
    chunk_text,
    split_reasoning,
)


def test_split_extracts_block_and_strips_it_from_answer():
    text = "<thinking>step one\nstep two</thinking>The final answer."
    reasoning, answer = split_reasoning(text)
    assert reasoning == "step one\nstep two"
    assert answer == "The final answer."
    assert "<thinking>" not in answer


def test_split_is_case_insensitive_and_spans_newlines():
    text = "<THINKING>\nmulti\nline\n</THINKING>\n\n## Summary\nx"
    reasoning, answer = split_reasoning(text)
    assert "multi" in reasoning and "line" in reasoning
    assert answer.startswith("## Summary")


def test_split_fallback_when_no_block():
    text = "Just an answer with no thinking block."
    reasoning, answer = split_reasoning(text)
    assert reasoning == ""
    assert answer == text


def test_split_fallback_when_block_unclosed_preserves_answer():
    # A truncated/unclosed block must never swallow the answer.
    text = "<thinking>partial reasoning that never closes ... answer body"
    reasoning, answer = split_reasoning(text)
    assert reasoning == ""
    assert answer == text


def test_split_empty_answer_keeps_original():
    # If removing the block leaves nothing, keep the original text as the answer.
    text = "<thinking>only reasoning here</thinking>"
    reasoning, answer = split_reasoning(text)
    assert reasoning == "only reasoning here"
    assert answer == text  # not empty


def test_split_handles_empty_input():
    assert split_reasoning("") == ("", "")


def test_chunk_text_splits_long_text():
    text = "x" * (MAX_THINKING_CHARS * 2 + 5)
    chunks = chunk_text(text)
    assert len(chunks) == 3
    assert all(len(c) <= MAX_THINKING_CHARS for c in chunks)
    assert "".join(chunks) == text


def test_chunk_text_empty_returns_empty_list():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_reasoning_instruction_mentions_thinking_tag():
    assert "<thinking>" in REASONING_INSTRUCTION
