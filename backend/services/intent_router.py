"""LLM-powered intent classifier for @jarvis mention text.

Routes free-text @jarvis phrases to structured actions using LLM classification
via freellmapi. Replaces the KNOWN_STAGES whitelist with open-vocabulary intent
recognition so team members can trigger SDLC actions using natural language.

Threat mitigations applied:
- T-02-05: Confidence threshold (<0.5) and VALID_ACTIONS membership guard filter
  low-confidence and unrecognised LLM outputs before they reach the pipeline.
- T-14-SC: No new packages installed; uses existing route_request infrastructure.
"""

import json
import logging
from dataclasses import dataclass, field

from services.llm_router import route_request

logger = logging.getLogger(__name__)

VALID_ACTIONS: frozenset[str] = frozenset({
    "describe",
    "architecture",
    "start_coding",
    "merge_pr",
    "assign",
    "approve",
})

_CLASSIFY_PROMPT = """\
You are an intent classifier for a Jira AI assistant called Jarvis.
Classify the following command into one of the valid actions.

Command: {mention_text}

Valid actions: {valid_actions}

Rules:
- If the command mentions approving something, use action "approve" and put the approval target in entities as {{"target": "<target text>"}}.
- If the command mentions assigning to someone, use action "assign" and put the person in entities as {{"user": "<name>"}}.
- If nothing matches, use action "unknown" with confidence 0.0.
- Confidence 1.0 = certain, 0.5 = borderline, 0.0 = no match.

Respond with ONLY valid JSON (no markdown, no explanation):
{{"action": "<action>", "confidence": <float>, "entities": {{}}}}"""


@dataclass
class IntentResult:
    """Structured result from LLM intent classification."""

    action: str
    confidence: float
    entities: dict = field(default_factory=dict)


def classify_intent(mention_text: str) -> "IntentResult | None":
    """Classify a free-text @jarvis phrase into a structured intent.

    Calls route_request('classify', ...) and parses the JSON response.
    Returns IntentResult when confidence >= 0.5 and action is valid.
    Returns None for low-confidence, unknown action, or any LLM failure.
    Never raises — LLM errors degrade gracefully to None.

    Args:
        mention_text: Text after the @jarvis mention (e.g. "approve story description").

    Returns:
        IntentResult or None.
    """
    prompt = _CLASSIFY_PROMPT.format(
        mention_text=mention_text,
        valid_actions=", ".join(sorted(VALID_ACTIONS)),
    )
    try:
        llm_response = route_request("classify", prompt)
        content = llm_response.content.strip()
        # Strip markdown code fences if the LLM wrapped the JSON
        if content.startswith("```"):
            lines = content.split("\n")
            end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            content = "\n".join(lines[1:end])
        data = json.loads(content)
        action = str(data.get("action", "unknown")).lower()
        confidence = float(data.get("confidence", 0.0))
        entities = dict(data.get("entities", {}))
    except Exception as exc:
        logger.warning("classify_intent failed for %r: %s", mention_text, exc)
        return None

    if confidence < 0.5 or action not in VALID_ACTIONS:
        return None

    return IntentResult(action=action, confidence=confidence, entities=entities)
