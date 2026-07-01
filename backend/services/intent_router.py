"""Keyword-based intent classifier for @jarvis mention text.

Maps fixed command phrases to structured actions. Commands are well-defined
so an LLM classifier adds latency and a failure point with no benefit.
"""

import re
from dataclasses import dataclass, field

VALID_ACTIONS: frozenset[str] = frozenset({
    "describe",
    "architecture",
    "start_coding",
    "merge_pr",
    "run_qa",
    "assign",
    "approve",
})

# Order matters: longer/more-specific patterns first.
_RULES: list[tuple[re.Pattern, str, dict]] = [
    (re.compile(r"approve\s+story\s+description", re.I), "approve", {"target": "story description"}),
    (re.compile(r"approve\s+architecture", re.I),        "approve", {"target": "architecture"}),
    (re.compile(r"approve\b",               re.I),       "approve", {}),
    (re.compile(r"start\s+coding",          re.I),       "start_coding", {}),
    (re.compile(r"merge\s+pr",              re.I),       "merge_pr", {}),
    (re.compile(r"run\s+qa",                re.I),       "run_qa", {}),
    (re.compile(r"architecture",            re.I),       "architecture", {}),
    (re.compile(r"describe",                re.I),       "describe", {}),
    (re.compile(r"assign\s+@?(\w+)",        re.I),       "assign", {}),
]


@dataclass
class IntentResult:
    action: str
    confidence: float
    entities: dict = field(default_factory=dict)


def classify_intent(mention_text: str) -> "IntentResult | None":
    """Match mention_text against known command patterns. Returns None if unrecognised."""
    text = mention_text.strip()
    for pattern, action, entities in _RULES:
        m = pattern.search(text)
        if m:
            extra_entities = dict(entities)
            if action == "assign" and m.lastindex:
                extra_entities["user"] = m.group(1)
            return IntentResult(action=action, confidence=1.0, entities=extra_entities)
    return None
