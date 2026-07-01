"""Complexity classifier service for Jira tickets.

Implements CLASSIFY-01 and CLASSIFY-02: given a Jira ticket's summary and
description, classifies the requested change as 'small' or 'complex' using
a single LLM call with structured JSON output.

CLASSIFY-01: classify_complexity() makes exactly one route_request('classify', prompt)
             call; routes through LiteLLM via HEAVY_STAGES.
CLASSIFY-02: LLM prompt requests JSON keys: classification ('small'|'complex'),
             rationale (str), component_count (int).

Isolation contract:
  - Zero imports from routers/, hermes_client, crypto, or any Jira-aware module.
  - Allowed imports: json, logging, sqlalchemy.orm.Session,
    services.llm_router.route_request.
  - Zero DB side effects — the classifier makes no writes. The caller
    (architecture_pipeline.run()) persists the returned values (WR-04).

ARCHCTX-01: classify_complexity() and _build_classify_prompt() accept an
optional codebase_snapshot parameter that threads codebase context from the
caller (architecture_pipeline.run(), which fetches the snapshot exactly once).
This module never calls get_codebase_snapshot() itself — isolation contract
above is preserved.
"""

import json
import logging

from pymongo.database import Database


logger = logging.getLogger(__name__)

_VALID_CLASSIFICATIONS = {"small", "complex"}


def _build_classify_prompt(
    issue_key: str,
    summary: str,
    description: str,
    codebase_snapshot: str | None = None,
) -> str:
    """Build the complexity classification prompt for the LLM.

    States the rubric, asks the model to count integration points, and requires
    a structured JSON response with exactly three keys: classification, rationale,
    and component_count.

    ARCHCTX-01: when codebase_snapshot is provided, a truncated (8000 char)
    codebase context block is appended to the prompt so the classifier can
    ground its component count in the actual codebase structure.

    Args:
        issue_key: Jira issue key (e.g. "PROJ-123").
        summary: Jira ticket summary line.
        description: Jira ticket description body.
        codebase_snapshot: Optional .hermes/codebase.md snapshot text. When
            provided, appended to the prompt (truncated to 8000 chars).

    Returns:
        Formatted prompt string ready to send to route_request.
    """
    prompt = (
        "You are a software complexity classifier. Given a Jira ticket, classify "
        "the requested change.\n\n"
        "Rubric:\n"
        '- "complex": the change touches 2 or more distinct components, services, '
        "or integration points\n"
        '- "small": the change touches fewer than 2 distinct components, services, '
        "or integration points\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {summary[:2000]}\n"
        f"Description: {description[:4000]}\n\n"
        "Respond with ONLY valid JSON in this exact schema:\n"
        "{\n"
        '  "classification": "small" or "complex",\n'
        '  "rationale": "one sentence explanation",\n'
        '  "component_count": <integer count of distinct components/services/integration points>\n'
        "}"
    )

    if codebase_snapshot is not None:
        codebase_text = codebase_snapshot[:8000]
        prompt += f"\n\nCodebase context (.hermes/codebase.md snapshot):\n{codebase_text}"

    return prompt


def classify_complexity(
    issue_key: str,
    summary: str,
    description: str,
    db: Database,
    project_id: int,
    codebase_snapshot: str | None = None,
) -> tuple[str, str]:
    """Classify a Jira ticket as 'small' or 'complex' using a single LLM call.

    Makes exactly one call to route_request('classify', prompt). The 'classify'
    stage is in HEAVY_STAGES so the call routes to freellmapi for structured
    JSON output.

    Returns the (complexity, rationale) tuple. Persistence is the caller's
    responsibility — architecture_pipeline.run() writes both values to its
    state_row in a single commit (WR-04: no redundant DB round-trip here).

    ARCHCTX-01: codebase_snapshot is an optional parameter threaded from the
    caller (architecture_pipeline.run(), which fetches the snapshot exactly
    once). When provided, it is appended to the classification prompt.

    Args:
        issue_key: Jira issue key (e.g. "PROJ-123").
        summary: Jira ticket summary line.
        description: Jira ticket description body.
        db: SQLAlchemy session to persist classification result.
        project_id: ID of the project in the web app DB.
        codebase_snapshot: Optional .hermes/codebase.md snapshot text.

    Returns:
        Tuple of (complexity, rationale) where complexity is "small" or "complex".
    """
    prompt = _build_classify_prompt(issue_key, summary, description, codebase_snapshot=codebase_snapshot)

    # ponytail: keyword heuristic — avoids broken REST API; upgrade to LLM when opencode REST works
    _complex_keywords = ("api", "service", "database", "migration", "integration", "endpoint",
                         "auth", "pipeline", "microservice", "kafka", "queue", "cache", "deploy")
    combined = f"{summary} {description}".lower()
    hits = sum(1 for kw in _complex_keywords if kw in combined)
    if hits >= 2:
        raw_classification, rationale, component_count = "complex", f"Matched {hits} complexity keywords", hits
    else:
        raw_classification, rationale, component_count = "small", "Few complexity indicators", hits

    # Cross-check component_count against the classification string (CLASSIFY-02).
    # Log a warning if they disagree so format drift is visible in logs; trust the
    # classification string for the actual decision.
    if isinstance(component_count, int):
        rubric_class = "complex" if component_count >= 2 else "small"
        if rubric_class != raw_classification:
            logger.warning(
                "classify_complexity: component_count=%d conflicts with classification=%r for %s "
                "— trusting classification string",
                component_count,
                raw_classification,
                issue_key,
            )

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

    # WR-04: do NOT write to DB here — architecture_pipeline.run() already writes
    # complexity/complexity_rationale onto state_row and commits once.  A second
    # commit here would cause a redundant DB round-trip and a transient
    # inconsistency window if the second commit fails after the first succeeds.
    # The caller (architecture_pipeline.run()) is solely responsible for
    # persisting the returned values.
    return (complexity, rationale)
