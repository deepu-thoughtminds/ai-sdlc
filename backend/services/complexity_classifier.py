"""Complexity classifier service for Jira tickets.

Implements CLASSIFY-01 and CLASSIFY-02: given a Jira ticket's summary and
description, classifies the requested change as 'small' or 'complex' using
a single freellmapi LLM call with structured JSON output.

CLASSIFY-01: classify_complexity() makes exactly one route_request('classify', prompt)
             call; routes through freellmapi via HEAVY_STAGES.
CLASSIFY-02: LLM prompt requests JSON keys: classification ('small'|'complex'),
             rationale (str), component_count (int).

Isolation contract:
  - Zero imports from routers/, hermes_client, crypto, or any Jira-aware module.
  - Allowed imports: json, logging, sqlalchemy.orm.Session,
    models.pipeline_state.PipelineState, services.llm_router.route_request.
  - DB side effects are limited to updating the most recent PipelineState row
    for (project_id, issue_key) via the caller's session — no direct DB
    connections or session creation.
"""

import json
import logging

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from services.llm_router import route_request

logger = logging.getLogger(__name__)

_VALID_CLASSIFICATIONS = {"small", "complex"}


def _build_classify_prompt(issue_key: str, summary: str, description: str) -> str:
    """Build the complexity classification prompt for the LLM.

    States the rubric, asks the model to count integration points, and requires
    a structured JSON response with exactly three keys: classification, rationale,
    and component_count.

    Args:
        issue_key: Jira issue key (e.g. "PROJ-123").
        summary: Jira ticket summary line.
        description: Jira ticket description body.

    Returns:
        Formatted prompt string ready to send to route_request.
    """
    return (
        "You are a software complexity classifier. Given a Jira ticket, classify "
        "the requested change.\n\n"
        "Rubric:\n"
        '- "complex": the change touches 2 or more distinct components, services, '
        "or integration points\n"
        '- "small": the change touches fewer than 2 distinct components, services, '
        "or integration points\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {summary}\n"
        f"Description: {description}\n\n"
        "Respond with ONLY valid JSON in this exact schema:\n"
        "{\n"
        '  "classification": "small" or "complex",\n'
        '  "rationale": "one sentence explanation",\n'
        '  "component_count": <integer count of distinct components/services/integration points>\n'
        "}"
    )


def classify_complexity(
    issue_key: str,
    summary: str,
    description: str,
    db: Session,
    project_id: int,
) -> tuple[str, str]:
    """Classify a Jira ticket as 'small' or 'complex' using a single LLM call.

    Makes exactly one call to route_request('classify', prompt). The 'classify'
    stage is in HEAVY_STAGES so the call routes to freellmapi for structured
    JSON output.

    Persists the classification result onto the most recent PipelineState row
    for (project_id, issue_key) if one exists. If no row exists, the caller
    is responsible for persisting the returned values.

    Args:
        issue_key: Jira issue key (e.g. "PROJ-123").
        summary: Jira ticket summary line.
        description: Jira ticket description body.
        db: SQLAlchemy session to persist classification result.
        project_id: ID of the project in the web app DB.

    Returns:
        Tuple of (complexity, rationale) where complexity is "small" or "complex".
    """
    prompt = _build_classify_prompt(issue_key, summary, description)

    # freellmapi routes classify to a deterministic model; temperature=0 enforced by HEAVY_STAGES routing
    # TODO: pass temperature=0 explicitly once route_request supports it (CLASSIFY-01)
    route_result = route_request("classify", prompt)

    try:
        parsed = json.loads(route_result.content)
        raw_classification = parsed["classification"]
        rationale = parsed.get("rationale", "")
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning(
            "classify_complexity: failed to parse LLM response for %s: %s — defaulting to small",
            issue_key,
            exc,
        )
        return ("small", "Classification unavailable — defaulting to small")

    # Validate classification value; default to 'small' if unexpected
    if raw_classification not in _VALID_CLASSIFICATIONS:
        logger.warning(
            "classify_complexity: unexpected classification value %r for %s — defaulting to small",
            raw_classification,
            issue_key,
        )
        complexity = "small"
    else:
        complexity = raw_classification

    # Persist onto the most recent PipelineState row for this (project_id, issue_key)
    state = (
        db.query(PipelineState)
        .filter_by(project_id=project_id, ticket_key=issue_key)
        .order_by(PipelineState.id.desc())
        .first()
    )
    if state is not None:
        state.complexity = complexity
        state.complexity_rationale = rationale
        db.commit()
    else:
        logger.debug(
            "classify_complexity: no PipelineState row found for project_id=%s issue_key=%s; "
            "skipping persistence — caller may not have created a row yet",
            project_id,
            issue_key,
        )

    return (complexity, rationale)
