"""Mention parser: extracts @jarvis mentions from Jira comment text.

Uses LLM-based intent classification (IntentRouter) instead of a static
KNOWN_STAGES whitelist, enabling free-text natural language commands.

Threat mitigations applied:
- T-02-02: Uses re.search with a bounded pattern; no eval or shell interpolation.
- T-02-05: LLM confidence threshold (<0.5) filters low-confidence classifications;
  unknown intents return None.
"""

import re
from dataclasses import dataclass, field

from services.intent_router import classify_intent


@dataclass
class MentionResult:
    """Result of a successful @jarvis mention parse."""

    mention_target: str  # "jarvis"
    action: str  # classified action (e.g. "architecture", "approve", "assign")
    extra: str = ""  # trailing tokens after the first keyword (backward compat)
    entities: dict = field(default_factory=dict)  # LLM-extracted entities


def parse_mention(comment_body: str) -> "MentionResult | None":
    """Parse @<agent> <command> from a comment body string.

    Uses the LLM intent classifier to map free-text commands to structured
    actions instead of matching against a static keyword whitelist.

    Returns MentionResult if a @<agent> mention is found and the LLM
    classifies it with sufficient confidence (>= 0.5).
    Returns None when no mention exists or the intent is unrecognised.

    Args:
        comment_body: Raw comment text (plain string for Walking Skeleton).

    Returns:
        MentionResult or None.
    """
    match = re.search(r"@(\w+)\s+(.*)", comment_body, re.DOTALL)
    if not match:
        return None

    mention_target = match.group(1)
    mention_text = match.group(2).strip()

    # Compute extra as the trailing text after the first keyword for backward
    # compatibility with callers that rely on mention_result.extra (e.g. assign_pipeline).
    parts = mention_text.split(None, 1)
    extra = parts[1].strip() if len(parts) > 1 else ""

    intent = classify_intent(mention_text)
    if intent is None:
        return None

    return MentionResult(
        mention_target=mention_target,
        action=intent.action,
        extra=extra,
        entities=intent.entities,
    )
