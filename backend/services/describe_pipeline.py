"""Description elaboration pipeline — DESCCTX-01 + DESCCTX-02.

Implements the describe stage pipeline:
  1. (DESCCTX-01) Read codebase snapshot from .hermes/codebase.md via get_codebase_snapshot()
  2. Fetch active sprint backlog from Jira REST API via hermes_client
  3. Assemble a prompt combining ticket info + snapshot context + sprint context
  4. Route to freellmapi via route_request("describe", prompt) — now in HEAVY_STAGES
  5. Return the generated description string

Uses codebase_snapshot_reader for codebase context.

Threat mitigations:
  T-03-02: Prompt assembled inline — decrypted token is only used for hermes_client
           calls, not included in the prompt string; only issue_key is logged.
  T-03-06: post_sprint_backlog handles all errors and returns [].
  T-20-01: github_repo slug decrypted with decrypt_credential; decrypted value
           never logged — only issue_key is logged. github_token used only for
           get_codebase_snapshot API call, not included in prompt.
  T-20-02: Snapshot text truncated to 8000 chars to prevent token overrun.
           When snapshot is None (unavailable), pipeline continues with fallback text.
"""

import logging
import os

from pymongo.database import Database

from models.project import Project
from services.codebase_snapshot_reader import get_codebase_snapshot
from services.crypto import decrypt_credential
from services.hermes_client import post_sprint_backlog
from services.llm_router import route_request
from services.reasoning import REASONING_INSTRUCTION, split_reasoning
from services.ticket_tracking import safe_record_agent_event, safe_record_reasoning

logger = logging.getLogger(__name__)


async def run(event: object, project: Project, db: Database) -> str:
    """Run the description elaboration pipeline for a Jira ticket.

    Steps:
    1. Decrypt project credentials and fetch codebase summary (DESC-01).
    2. Fetch active sprint backlog (DESC-02) — graceful on error (returns []).
    3. Assemble a structured prompt with all available context.
    4. Call route_request("describe", prompt) — routes to freellmapi.
    5. Return the generated description text.

    T-03-02: decrypted tokens used only for API calls, never included in prompt.

    Args:
        event: JiraCommentEvent (or compatible duck-typed object) with
               issue.key, issue.fields["summary"], and comment.body attributes.
        project: Project ORM object with jira_url, jira_token, github_url,
                 github_token, and project_key fields.

    Returns:
        The LLM-generated description string.
    """
    # --- Step 1 (DESCCTX-01): Fetch codebase snapshot from .hermes/codebase.md ---
    _issue_key_early = getattr(getattr(event, "issue", None), "key", "UNKNOWN")

    try:
        github_token = decrypt_credential(project.github_token) if project.github_token else ""
    except Exception as exc:
        logger.warning(
            "Failed to decrypt github_token for issue %s — snapshot skipped: %s",
            _issue_key_early,
            exc,
        )
        github_token = ""

    # T-20-01: decrypt github_repo slug; decrypted value never logged
    try:
        github_repo = decrypt_credential(project.github_repo)
    except Exception as exc:
        logger.warning(
            "Failed to decrypt github_repo for issue %s — snapshot skipped: %s",
            _issue_key_early,
            exc,
        )
        github_repo = ""

    snapshot = await get_codebase_snapshot(github_repo, github_token)

    # --- Step 2 (DESC-02): Fetch sprint backlog ---
    try:
        jira_token = decrypt_credential(project.jira_token)
    except Exception:
        jira_token = ""

    jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
    # T-03-06: all errors caught inside post_sprint_backlog; returns [] on failure
    backlog = await post_sprint_backlog(project.jira_url, jira_email, jira_token, project.project_key)

    # --- Step 3: Assemble prompt ---
    # Sprint context
    backlog_text = (
        "\n".join(f"- {i['key']}: {i['summary']} ({i['issue_type']})" for i in backlog)
        or "(no active sprint tickets)"
    )

    # T-20-02: truncate to 8000 chars to prevent token overrun; fallback when None
    codebase_text = snapshot[:8000] if snapshot else "(no codebase context available)"

    # Ticket info from the event
    issue_key = getattr(event.issue, "key", "UNKNOWN")  # type: ignore[union-attr]
    # Use .summary directly — JiraIssue now has summary as a top-level field
    # (flattened from issue.fields.summary in the webhook model validator)
    ticket_title = getattr(event.issue, "summary", None) or issue_key  # type: ignore[union-attr]
    # T-03-02: comment body from Jira; cap here as a defence-in-depth guard
    trigger_comment = (getattr(event.comment, "body", "") or "")[:4000]  # type: ignore[union-attr]

    prompt = (
        f"You are a senior product manager. Elaborate the following Jira ticket into a clear, "
        f"complete feature description.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {ticket_title}\n"
        f"Current description / trigger comment:\n{trigger_comment}\n\n"
        f"Sprint backlog context (related tickets in same sprint):\n{backlog_text}\n\n"
        f"Codebase context (.hermes/codebase.md snapshot):\n{codebase_text}\n\n"
        f"Write an elaborated feature description (3-5 paragraphs) covering: user value, "
        f"acceptance criteria, technical scope, and any integration points visible in the "
        f"codebase. Reference specific module names and file paths from the codebase context "
        f"where relevant. Output only the description text."
        + REASONING_INSTRUCTION
    )

    # Record the context-gathering steps as agent actions (best-effort).
    safe_record_agent_event(
        db, project.id, issue_key, "description", "action", "Read codebase snapshot",
        detail=f"{len(snapshot)} chars" if snapshot else "no snapshot available",
    )
    safe_record_agent_event(
        db, project.id, issue_key, "description", "action", "Fetched sprint backlog",
        detail=f"{len(backlog)} ticket(s)",
    )

    # --- Step 4: Route to LLM (HEAVY_STAGES includes "describe") ---
    logger.info("Running describe pipeline for issue %s", issue_key)
    response = route_request("describe", prompt)

    # Split the model's <thinking> reasoning from the description it should post.
    reasoning, answer = split_reasoning(response.content)
    if response.reasoning:  # native reasoning tokens take precedence when present
        reasoning = response.reasoning
    safe_record_reasoning(db, project.id, issue_key, "description", reasoning)
    safe_record_agent_event(
        db, project.id, issue_key, "description", "goal", "Description drafted",
    )

    return answer
