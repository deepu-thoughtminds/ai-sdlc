"""Architecture pipeline service — ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-03.

Single-pass, complexity-aware architecture pipeline that:
  1. Creates a PipelineState row immediately (status="running") for idempotency.
  2. Classifies the ticket as "small" or "complex" via complexity_classifier.
  3. Generates a recommended architecture (NOT multiple options).
  4. For "complex" tickets: generates a drawio diagram and calls publish_architecture
     with is_complex=True.
  5. For "small" tickets: skips diagram generation and calls publish_architecture
     with is_complex=False.
  6. Posts a final Jira comment string. Sets PipelineState.status="complete".

Threat mitigations:
  T-04-01: prompt contains only issue_key/summary/description — no token values
           are ever interpolated into the LLM prompt.
  T-04-03: Confluence publish failure is caught and degraded (page_url = "");
           pipeline continues and posts Jira comment without URL.
"""

import logging
import os

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from services.complexity_classifier import classify_complexity
from services.confluence_client import publish_architecture
from services.crypto import decrypt_credential
from services.drawio_service import generate_diagram, generate_viewer_url
from services.hermes_client import post_comment as hermes_post_comment
from services.llm_router import route_request

logger = logging.getLogger(__name__)

# Prefix applied to all agent-generated Jira comments.
AGENT_COMMENT_PREFIX = "🤖 **Jarvis:**\n\n"

# Plain-ASCII marker embedded in every agent comment body.
AGENT_BODY_MARKER = "[jarvis-bot]"


def _parse_sections(llm_output: str, section_names: list[str]) -> dict[str, str]:
    """Parse labelled sections from LLM output into a dict.

    Splits on lines that start with "## ". Each recognised section name is
    mapped to the text that follows it until the next "## " heading or end of
    string.

    Missing sections return "". Never raises — malformed LLM output is handled
    gracefully.

    Args:
        llm_output: Raw LLM response text.
        section_names: Ordered list of expected section names (without "## ").

    Returns:
        Dict mapping each section name to its extracted content string (stripped).
    """
    result: dict[str, str] = {name: "" for name in section_names}

    lines = llm_output.split("\n")
    current_section: str | None = None
    accumulated: list[str] = []

    def _flush() -> None:
        if current_section is not None and current_section in result:
            result[current_section] = "\n".join(accumulated).strip()

    for line in lines:
        if line.startswith("## "):
            _flush()
            accumulated = []
            heading = line[3:].strip()
            # Match the heading to a known section (case-insensitive).
            current_section = None
            for name in section_names:
                if name.lower() == heading.lower():
                    current_section = name
                    break
        else:
            accumulated.append(line)

    _flush()
    return result


async def run(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    db: Session,
) -> str:
    """Run the single-pass complexity-aware architecture pipeline for a ticket.

    ARCHGEN-01: Classifies complexity (small / complex) before generating architecture.
    ARCHGEN-02: For complex tickets, generates a drawio diagram.
    ARCHGEN-03: Publishes a single recommended architecture to Confluence (find-or-update).
    ARCHINT-03: No multi-option flow — one recommended architecture only.

    T-04-01: prompt contains only issue_key/summary/description — no token values.
    T-04-03: Confluence publish failure is caught; pipeline continues without URL.

    Args:
        project: Project ORM with jira_url, confluence_url, encrypted tokens.
        issue_key: Jira issue key (e.g. "PROJ-1").
        issue_summary: Issue summary field.
        issue_description: Issue description field (plain text).
        db: SQLAlchemy session for PipelineState persistence.

    Returns:
        Final architecture comment text posted to Jira.
    """
    logger.info("Architecture pipeline started for ticket %s", issue_key)

    # Step 1: Re-use the PipelineState row created by the webhook idempotency
    # guard (webhook.py creates it with status="running" BEFORE scheduling this
    # task). If no row found (e.g. direct call in tests), create one.
    state_row = (
        db.query(PipelineState)
        .filter(
            PipelineState.ticket_key == issue_key,
            PipelineState.stage == "architecture",
            PipelineState.status == "running",
        )
        .order_by(PipelineState.created_at.desc())
        .first()
    )
    if state_row is None:
        state_row = PipelineState(
            project_id=project.id,
            ticket_key=issue_key,
            stage="architecture",
            status="running",
        )
        db.add(state_row)
        db.commit()

    comment_text = ""
    try:
        # Step 2: Classify the ticket complexity.
        complexity, rationale = classify_complexity(
            issue_key, issue_summary, issue_description, db, project.id
        )
        state_row.complexity = complexity
        state_row.complexity_rationale = rationale
        db.commit()

        logger.info(
            "Ticket %s classified as %r — %s", issue_key, complexity, rationale
        )

        if complexity == "complex":
            comment_text = await _run_complex(
                project, issue_key, issue_summary, issue_description
            )
        else:
            comment_text = await _run_simple(
                project, issue_key, issue_summary, issue_description
            )

        # Step 3: Post the architecture comment to Jira BEFORE finalising state.
        # WR-01: posting first avoids a window where status="complete" but the
        # user has not yet received the comment (e.g. if the Jira call fails
        # after the commit, the idempotency guard would block any retry).
        try:
            jira_token = decrypt_credential(project.jira_token)
            jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
            await hermes_post_comment(
                project.jira_url,
                jira_email,
                jira_token,
                issue_key,
                AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + comment_text,
            )
        except Exception as exc:
            logger.warning("Failed to post architecture comment for ticket %s: %s", issue_key, exc)

        # Step 4: Finalise the state row only after the Jira comment has been posted.
        state_row.status = "complete"
        state_row.draft_content = comment_text
        db.commit()

    except Exception as exc:
        state_row.status = "failed"
        try:
            db.commit()
        except Exception:
            db.rollback()
        # WR-03: Notify user in Jira so the failure is visible without monitoring server logs.
        try:
            jira_token = decrypt_credential(project.jira_token)
            jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
            await hermes_post_comment(
                project.jira_url,
                jira_email,
                jira_token,
                issue_key,
                AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n"
                + "Architecture generation failed. Please retry with `@jarvis architecture`.",
            )
        except Exception:
            pass
        logger.exception("Architecture pipeline failed for ticket %s: %s", issue_key, exc)
        # Do not re-raise — the background task has no outer exception handler,
        # so re-raising would silently swallow the exception as an unhandled task exception.

    logger.info("Architecture pipeline complete for ticket %s", issue_key)
    return comment_text


async def _run_complex(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
) -> str:
    """Execute the complex-ticket branch of the architecture pipeline.

    Requests six labelled sections from the LLM, generates a drawio diagram,
    and publishes to Confluence with is_complex=True.

    T-04-01: only issue_key/summary/description are included in the prompt.

    Returns:
        Human-readable Jira comment text.
    """
    # Build prompt for complex architecture.
    prompt = (
        "You are a software architect. Generate ONE recommended architecture for "
        "the following Jira ticket. Do NOT generate multiple options.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {issue_summary}\n"
        f"Description: {issue_description}\n\n"
        "Respond with exactly these six labelled sections in this order:\n\n"
        "## Summary\n"
        "[1-2 sentence overview of the recommended architecture]\n\n"
        "## Approach\n"
        "[Technical approach and key design patterns]\n\n"
        "## Component Breakdown\n"
        "[Comma-separated or newline-separated list of components/services involved]\n\n"
        "## Integration Points\n"
        "[Key integration points and interfaces between components]\n\n"
        "## Key Decisions\n"
        "[Important architectural decisions and their rationale]\n\n"
        "## Risks\n"
        "[Key risks and mitigation strategies]"
    )

    section_names = [
        "Summary",
        "Approach",
        "Component Breakdown",
        "Integration Points",
        "Key Decisions",
        "Risks",
    ]

    route_result = route_request("architecture", prompt)
    sections = _parse_sections(route_result.content, section_names)

    summary = sections["Summary"]
    approach = sections["Approach"]
    component_breakdown = sections["Component Breakdown"]
    integration_points = sections["Integration Points"]
    key_decisions = sections["Key Decisions"]
    risks = sections["Risks"]

    # Extract component names for the diagram (split on commas and newlines).
    component_list: list[str] = [
        c.strip()
        for line in component_breakdown.replace(",", "\n").splitlines()
        for c in [line.strip()]
        if c and not c.startswith("#")
    ]
    if not component_list:
        component_list = ["Component"]

    # Generate the drawio diagram (mxGraph XML + viewer URL).
    diagram_xml = generate_diagram(
        title=f"Architecture: {issue_key}",
        components=component_list,
        connections=[],
    )
    viewer_url = generate_viewer_url(diagram_xml)

    # Publish to Confluence (graceful degradation on failure — T-04-03).
    page_url = ""
    try:
        page_url = await publish_architecture(
            project,
            issue_key,
            summary,
            approach,
            key_decisions,
            risks,
            is_complex=True,
            component_breakdown=component_breakdown,
            integration_points=integration_points,
            diagram_xml=diagram_xml,
            viewer_url=viewer_url,
        )
    except Exception as exc:
        logger.warning(
            "Confluence publishing failed for ticket %s: %s", issue_key, exc
        )

    if page_url:
        comment_text = (
            f"*Architecture for {issue_key}*\n\n"
            f"{summary}\n\n"
            f"Multi-component feature — diagram included.\n\n"
            f"Confluence: {page_url}"
        )
    else:
        comment_text = (
            f"*Architecture for {issue_key}*\n\n"
            f"{summary}\n\n"
            f"Multi-component feature — diagram included.\n\n"
            f"(Confluence publishing unavailable)"
        )

    return comment_text


async def _run_simple(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
) -> str:
    """Execute the simple-ticket branch of the architecture pipeline.

    Requests four labelled sections from the LLM. Does NOT call generate_diagram.
    Publishes to Confluence with is_complex=False.

    T-04-01: only issue_key/summary/description are included in the prompt.

    Returns:
        Human-readable Jira comment text.
    """
    # Build prompt for simple architecture.
    prompt = (
        "You are a software architect. Generate ONE recommended architecture for "
        "the following Jira ticket. Do NOT generate multiple options.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {issue_summary}\n"
        f"Description: {issue_description}\n\n"
        "Respond with exactly these four labelled sections in this order:\n\n"
        "## Summary\n"
        "[1-2 sentence overview of the recommended architecture]\n\n"
        "## Approach\n"
        "[Technical approach and key design patterns]\n\n"
        "## Key Decisions\n"
        "[Important architectural decisions and their rationale]\n\n"
        "## Risks\n"
        "[Key risks and mitigation strategies]"
    )

    section_names = ["Summary", "Approach", "Key Decisions", "Risks"]

    route_result = route_request("architecture", prompt)
    sections = _parse_sections(route_result.content, section_names)

    summary = sections["Summary"]
    approach = sections["Approach"]
    key_decisions = sections["Key Decisions"]
    risks = sections["Risks"]

    # Publish to Confluence — text-only template (T-04-03: graceful degradation).
    page_url = ""
    try:
        page_url = await publish_architecture(
            project,
            issue_key,
            summary,
            approach,
            key_decisions,
            risks,
            is_complex=False,
        )
    except Exception as exc:
        logger.warning(
            "Confluence publishing failed for ticket %s: %s", issue_key, exc
        )

    if page_url:
        comment_text = (
            f"*Architecture for {issue_key}*\n\n"
            f"{summary}\n\n"
            f"Simple change — text architecture.\n\n"
            f"Confluence: {page_url}"
        )
    else:
        comment_text = (
            f"*Architecture for {issue_key}*\n\n"
            f"{summary}\n\n"
            f"Simple change — text architecture.\n\n"
            f"(Confluence publishing unavailable)"
        )

    return comment_text
