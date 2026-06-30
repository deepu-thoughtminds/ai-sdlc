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

Phase 34 migration:
  - route_request() replaced by _run_opencode_arch() — opencode CLI subprocess.
  - get_codebase_snapshot() replaced by _query_arch_context() — cbm graph search.
  AGENT-05: no direct opencode.ai API calls remain in this pipeline.
  CTX-03: graph queried via _query_arch_context() before pipeline runs.

Threat mitigations:
  T-04-01: prompt contains only issue_key/summary/description — no token values
           are ever interpolated into the LLM prompt.
  T-04-03: Confluence publish failure is caught and degraded (page_url = "");
           pipeline continues and posts Jira comment without URL.
  T-21-01: github_token and github_repo decrypted values never logged — only
           issue_key is logged in all logger calls.
  T-21-02: Graph context text truncated to 8000 chars to prevent token overrun.
           When graph context is unavailable, pipeline continues with fallback text
           "(no codebase context available)".

ARCHCTX-01: run() queries codebase graph via _query_arch_context() exactly once,
then passes the result to both classify_complexity() and
_run_complex()/_run_simple() (ARCHCTX-02).
"""

import asyncio
import json
import logging
import os
import tempfile

from pymongo.database import Database

from models.project import Project
from repositories import pipeline_state_repo
from services.agentic_coder import _opencode_config
from services.cbm_client import cbm_call
from services.complexity_classifier import classify_complexity
from services.confluence_client import publish_architecture
from services.crypto import decrypt_credential
from services.reasoning import REASONING_INSTRUCTION, split_reasoning
from services.ticket_tracking import (
    safe_record_agent_event,
    safe_record_reasoning,
    safe_record_transaction,
    safe_upsert_ticket_status,
)
from services.drawio_service import generate_diagram, generate_viewer_url
from services.hermes_client import post_comment as hermes_post_comment

logger = logging.getLogger(__name__)

# Prefix applied to all agent-generated Jira comments.
AGENT_COMMENT_PREFIX = "🤖 **Jarvis:**\n\n"

# Plain-ASCII marker embedded in every agent comment body.
AGENT_BODY_MARKER = "[jarvis-bot]"


async def _run_opencode_arch(prompt: str) -> tuple[str, str]:
    """Invoke opencode CLI for an architecture-generation prompt.

    Mirrors _run_opencode_describe from describe_pipeline.py.

    Returns (content, reasoning) where content is the joined assistant text
    and reasoning is empty string (opencode CLI does not expose reasoning tokens
    separately; split_reasoning in the caller handles <thinking> blocks).

    Degrades gracefully: returns ("", "") on timeout or subprocess failure.
    """
    model = os.environ.get("OPENCODE_MODEL", "opencode/deepseek-v4-flash-free")
    opencode_bin = os.environ.get("OPENCODE_BIN", "opencode")
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            opencode_bin, "run", prompt,
            "--model", model,
            "--dir", tmpdir,
            "--dangerously-skip-permissions",
            "--format", "json",
        ]
        env = {**os.environ, "OPENCODE_CONFIG_CONTENT": _opencode_config()}
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except asyncio.TimeoutError:
            logger.warning("opencode CLI timed out for architecture prompt")
            proc.kill()
            await proc.wait()
            return "", ""
        except Exception as exc:
            logger.warning("opencode CLI failed for architecture: %s", exc)
            return "", ""

        text_parts: list[str] = []
        for line in stdout_bytes.decode(errors="replace").splitlines():
            try:
                ev = json.loads(line)
                if ev.get("type") == "assistant":
                    for part in ev.get("content", []):
                        if part.get("type") == "text" and part.get("text"):
                            text_parts.append(part["text"].strip())
            except (json.JSONDecodeError, TypeError):
                pass
        return "\n\n".join(text_parts), ""


async def _query_arch_context(issue_summary: str) -> str:
    """Query codebase graph via cbm_call for architecture context.

    CTX-03: called once in run() before the architecture pipeline runs.

    Returns graph node text string, or a fallback string on failure.
    """
    try:
        graph_result = await asyncio.to_thread(
            cbm_call,
            "search_graph",
            {"query": issue_summary, "limit": 20},
        )
        nodes = graph_result.get("nodes", graph_result.get("results", []))
        if nodes:
            return "\n".join(
                f"- {n.get('name', n.get('id', ''))} ({n.get('file', n.get('path', ''))})"
                for n in nodes[:20]
            )
        return "(no graph context available)"
    except Exception as exc:
        logger.warning("cbm search_graph failed for arch context: %s", exc)
        return "(codebase graph unavailable)"


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
            if result[current_section]:
                logger.warning(
                    "_parse_sections: duplicate heading %r — overwriting previous content",
                    current_section,
                )
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
            if current_section is None:
                logger.warning(
                    "_parse_sections: unrecognised heading %r — content will be dropped",
                    heading,
                )
        else:
            accumulated.append(line)

    _flush()
    return result


async def run(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    db: Database,
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
    state_row = pipeline_state_repo.find_latest(
        db, ticket_key=issue_key, stage="architecture", statuses=["running"]
    )
    if state_row is None:
        state_row = pipeline_state_repo.create(
            db, project.id, issue_key, "architecture", status="running"
        )

    comment_text = ""
    try:
        # Step 1.5 (ARCHCTX-01 / CTX-03): query codebase graph via cbm once.
        # T-21-01: no token values are logged — only issue_key.
        graph_context = await _query_arch_context(issue_summary)
        safe_record_agent_event(
            db, project.id, issue_key, "architecture", "action", "Queried codebase graph",
            detail=f"{len(graph_context)} chars" if graph_context else "no graph context",
        )

        # Step 2: Classify the ticket complexity.
        complexity, rationale = classify_complexity(
            issue_key, issue_summary, issue_description, db, project.id,
            codebase_snapshot=graph_context,
        )
        pipeline_state_repo.update(
            db, state_row.id, complexity=complexity, complexity_rationale=rationale
        )
        safe_record_agent_event(
            db, project.id, issue_key, "architecture", "decision",
            f"Classified as {complexity}", detail=rationale,
        )

        logger.info(
            "Ticket %s classified as %r — %s", issue_key, complexity, rationale
        )

        if complexity == "complex":
            comment_text = await _run_complex(
                project, issue_key, issue_summary, issue_description, graph_context, db
            )
        else:
            comment_text = await _run_simple(
                project, issue_key, issue_summary, issue_description, graph_context, db
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
        pipeline_state_repo.update(
            db, state_row.id, status="complete", draft_content=comment_text
        )

        # Ticket-tracking bookkeeping (best-effort). The Confluence page link is
        # embedded in comment_text, stored here as detail.
        safe_upsert_ticket_status(
            db, project.id, issue_key,
            pipeline_stage="architecture",
            current_status="Design/Architecture published to Confluence",
        )
        safe_record_transaction(
            db, project.id, issue_key, "architecture",
            "Design/Architecture published to Confluence page",
            status="success", detail=comment_text,
        )
        safe_record_agent_event(
            db, project.id, issue_key, "architecture", "goal", "Architecture published",
        )

    except Exception as exc:
        pipeline_state_repo.update(db, state_row.id, status="failed")
        safe_upsert_ticket_status(
            db, project.id, issue_key,
            pipeline_stage="architecture", current_status="Architecture generation failed",
        )
        safe_record_transaction(
            db, project.id, issue_key, "architecture",
            "Architecture generation failed", status="failed", detail=str(exc),
        )
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
        except Exception as notify_exc:
            logger.warning(
                "Failed to post failure-notification comment for ticket %s: %s",
                issue_key,
                notify_exc,
            )
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
    graph_context: str | None,
    db: Database,
) -> str:
    """Execute the complex-ticket branch of the architecture pipeline.

    Requests six labelled sections from the LLM via opencode CLI, generates a
    drawio diagram, and publishes to Confluence with is_complex=True.

    T-04-01: only issue_key/summary/description are included in the prompt.
    T-21-02: graph context truncated to 8000 chars; fallback text used when None.

    Args:
        graph_context: Codebase graph text fetched once in run() (ARCHCTX-01),
            or None when unavailable.

    Returns:
        Human-readable Jira comment text.
    """
    codebase_text = graph_context[:8000] if graph_context else "(no codebase context available)"

    # Build prompt for complex architecture.
    # T-WR-02: truncate summary/description to prevent token overrun.
    prompt = (
        "You are a software architect. Generate ONE recommended architecture for "
        "the following Jira ticket. Do NOT generate multiple options.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {issue_summary[:2000]}\n"
        f"Description: {issue_description[:4000]}\n\n"
        f"Codebase context (module graph):\n{codebase_text}\n\n"
        "Reference specific module names and file paths from the codebase context "
        "where relevant.\n\n"
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
        + REASONING_INSTRUCTION
    )

    section_names = [
        "Summary",
        "Approach",
        "Component Breakdown",
        "Integration Points",
        "Key Decisions",
        "Risks",
    ]

    content, _ = await _run_opencode_arch(prompt)
    reasoning, answer = split_reasoning(content)
    safe_record_reasoning(db, project.id, issue_key, "architecture", reasoning)
    sections = _parse_sections(answer, section_names)

    # If the LLM skipped the ## headings the parser returns all-empty sections.
    # Fall back to raw output so the page is never blank.
    if not any(sections.values()):
        logger.warning(
            "Architecture LLM output for %s contained no ## sections — using raw output as summary",
            issue_key,
        )
        sections["Summary"] = answer or "(no architecture generated)"

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
    safe_record_agent_event(
        db, project.id, issue_key, "architecture", "action", "Generated architecture diagram",
        detail=f"{len(component_list)} component(s)",
    )

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
        safe_record_agent_event(
            db, project.id, issue_key, "architecture", "action",
            "Published architecture to Confluence", detail=page_url,
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
    graph_context: str | None,
    db: Database,
) -> str:
    """Execute the simple-ticket branch of the architecture pipeline.

    Requests four labelled sections from the LLM via opencode CLI. Does NOT call
    generate_diagram. Publishes to Confluence with is_complex=False.

    T-04-01: only issue_key/summary/description are included in the prompt.
    T-21-02: graph context truncated to 8000 chars; fallback text used when None.

    Args:
        graph_context: Codebase graph text fetched once in run() (ARCHCTX-01),
            or None when unavailable.

    Returns:
        Human-readable Jira comment text.
    """
    codebase_text = graph_context[:8000] if graph_context else "(no codebase context available)"

    # Build prompt for simple architecture.
    # T-WR-02: truncate summary/description to prevent token overrun.
    prompt = (
        "You are a software architect. Generate ONE recommended architecture for "
        "the following Jira ticket. Do NOT generate multiple options.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {issue_summary[:2000]}\n"
        f"Description: {issue_description[:4000]}\n\n"
        f"Codebase context (module graph):\n{codebase_text}\n\n"
        "Reference specific module names and file paths from the codebase context "
        "where relevant.\n\n"
        "Respond with exactly these four labelled sections in this order:\n\n"
        "## Summary\n"
        "[1-2 sentence overview of the recommended architecture]\n\n"
        "## Approach\n"
        "[Technical approach and key design patterns]\n\n"
        "## Key Decisions\n"
        "[Important architectural decisions and their rationale]\n\n"
        "## Risks\n"
        "[Key risks and mitigation strategies]"
        + REASONING_INSTRUCTION
    )

    section_names = ["Summary", "Approach", "Key Decisions", "Risks"]

    content, _ = await _run_opencode_arch(prompt)
    reasoning, answer = split_reasoning(content)
    safe_record_reasoning(db, project.id, issue_key, "architecture", reasoning)
    sections = _parse_sections(answer, section_names)

    if not any(sections.values()):
        logger.warning(
            "Architecture LLM output for %s contained no ## sections — using raw output as summary",
            issue_key,
        )
        sections["Summary"] = answer or "(no architecture generated)"

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
        safe_record_agent_event(
            db, project.id, issue_key, "architecture", "action",
            "Published architecture to Confluence", detail=page_url,
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
