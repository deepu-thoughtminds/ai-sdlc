"""Shared helpers for capturing an LLM stage's reasoning as agent "thinking".

freellmapi's free providers don't return native reasoning tokens, so for the
single-shot `route_request` stages we ask the model to emit its step-by-step
reasoning inside a `<thinking>…</thinking>` block at the start of its response,
then split that block off before using the answer.

Two pieces:
  REASONING_INSTRUCTION — append to any heavy-stage prompt.
  split_reasoning()     — pull the <thinking> block out, returning (reasoning, answer).

Robustness is the contract: a model that ignores the instruction (or gets cut
off mid-block) must never break the stage, so split_reasoning falls back to
("", original_text) — the answer is always preserved and the <thinking> markup
is never left in the text that gets posted to Jira/Confluence.
"""

import re

# Cap a single thinking event's content (mirrors agentic_coder._MAX_EVENT_CHARS).
MAX_THINKING_CHARS = 2000

REASONING_INSTRUCTION = (
    "\n\nBefore your final answer, reason step by step about how you will "
    "approach this. Put that reasoning inside a single <thinking>...</thinking> "
    "block at the very START of your response. After the closing </thinking> "
    "tag, output ONLY the required result with no further commentary and without "
    "repeating the reasoning."
)

# Match <thinking>…</thinking> OR <think>…</think> (DeepSeek/QwQ style).
_THINKING_RE = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.IGNORECASE | re.DOTALL)


def split_reasoning(text: str) -> tuple[str, str]:
    """Split a model response into (reasoning, answer).

    Extracts the first complete <thinking>…</thinking> block as the reasoning and
    returns the remaining text (block removed, stripped) as the answer. If no
    complete block is present, returns ("", text) so the answer is never lost.
    """
    if not text:
        return "", text
    match = _THINKING_RE.search(text)
    if not match:
        return "", text
    reasoning = match.group(1).strip()
    answer = (text[: match.start()] + text[match.end():]).strip()
    # Guard: if stripping the block left nothing usable, keep the original text
    # as the answer rather than posting an empty description.
    if not answer:
        return reasoning, text
    return reasoning, answer


def chunk_text(text: str, size: int = MAX_THINKING_CHARS) -> list[str]:
    """Split text into <= size chunks (so long reasoning maps to several events)."""
    text = (text or "").strip()
    if not text:
        return []
    return [text[i: i + size] for i in range(0, len(text), size)]
