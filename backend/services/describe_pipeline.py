"""Description elaboration pipeline — DESC-01 + DESC-02.

Implements the describe stage pipeline:
  1. (DESC-01) Fetch structured codebase summary from GitHub via graphify_service
  2. (DESC-02) Fetch active sprint backlog from Jira REST API via JiraClient
  3. Assemble a prompt combining ticket info + codebase context + sprint context
  4. Route to freellmapi via route_request("describe", prompt) — now in HEAVY_STAGES
  5. Return the generated description string

Threat mitigations:
  T-03-02: Prompt assembled inline — decrypted token is only used to construct
           JiraClient, not included in the prompt string; only issue_key is logged.
  T-03-06: JiraClient.get_sprint_backlog handles all errors and returns [].
"""

import logging
import os

from models.project import Project
from services.crypto import decrypt_credential
from services.graphify_service import get_codebase_summary
from services.jira_client import JiraClient
from services.llm_router import route_request

logger = logging.getLogger(__name__)


async def run(event: object, project: Project) -> str:
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
    # --- Step 1 (DESC-01): Fetch codebase summary ---
    try:
        github_token = decrypt_credential(project.github_token) if project.github_token else ""
    except Exception:
        github_token = ""

    github_url = getattr(project, "github_url", None) or ""
    summary = get_codebase_summary(github_url, github_token)

    # --- Step 2 (DESC-02): Fetch sprint backlog ---
    try:
        jira_token = decrypt_credential(project.jira_token)
    except Exception:
        jira_token = ""

    jira_email = os.environ.get("JIRA_ACCOUNT_EMAIL", "")
    client = JiraClient(project.jira_url, jira_token, jira_email)
    # T-03-06: all errors caught inside get_sprint_backlog; returns [] on failure
    backlog = client.get_sprint_backlog(project.project_key)

    # --- Step 3: Assemble prompt ---
    # Sprint context
    backlog_text = (
        "\n".join(f"- {i['key']}: {i['summary']} ({i['issue_type']})" for i in backlog)
        or "(no active sprint tickets)"
    )

    # Codebase context (truncate to avoid token limit overrun)
    codebase_text = summary.directory_tree[:3000] if summary.directory_tree else "(no codebase context available)"
    key_files_text = "\n".join(summary.key_files[:10]) if summary.key_files else "(none)"

    # Ticket info from the event
    issue_key = getattr(event.issue, "key", "UNKNOWN")  # type: ignore[union-attr]
    fields = getattr(event.issue, "fields", {}) or {}  # type: ignore[union-attr]
    ticket_title = fields.get("summary", issue_key) if isinstance(fields, dict) else issue_key
    # T-03-02: comment body from Jira (validated at webhook layer, max 10000 chars)
    trigger_comment = getattr(event.comment, "body", "") or ""  # type: ignore[union-attr]

    prompt = (
        f"You are a senior product manager. Elaborate the following Jira ticket into a clear, "
        f"complete feature description.\n\n"
        f"Ticket: {issue_key}\n"
        f"Summary: {ticket_title}\n"
        f"Current description / trigger comment:\n{trigger_comment}\n\n"
        f"Sprint backlog context (related tickets in same sprint):\n{backlog_text}\n\n"
        f"Codebase structure (for technical context):\n{codebase_text}\n\n"
        f"Key Python modules:\n{key_files_text}\n\n"
        f"Write an elaborated feature description (3-5 paragraphs) covering: user value, "
        f"acceptance criteria, technical scope, and any integration points visible in the "
        f"codebase. Output only the description text."
    )

    # --- Step 4: Route to LLM (HEAVY_STAGES includes "describe") ---
    logger.info("Running describe pipeline for issue %s", issue_key)
    response = route_request("describe", prompt)

    return response.content
