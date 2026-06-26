"""Approval detector service for the description and architecture pipelines.

Detects @jarvis approve <subcmd> mentions and applies the approved content
to the Jira ticket. Approval is now entirely mention-based — keyword-based
detection (APPROVAL_KEYWORDS / is_approval) has been removed.

Approval sub-commands (APPROVE_SUBCMDS in mention_parser):
  - "story description" → update Jira ticket description field
  - "architecture"      → architecture approval (reserved for future use)

Sub-command validation happens in mention_parser.parse_mention before this
module is called, so unknown sub-commands never reach detect_and_apply_approval.

Threat mitigations:
  T-o0v-03: approve_subcmd validated against APPROVE_SUBCMDS frozenset in
             mention_parser before routing here; unknown sub-commands → None.
  T-03-14: detect_and_apply_approval returns False immediately on unknown
           sub-command or missing pending state — single pass, no retries.
  T-09-01: jira_token never logged; only issue_key logged at INFO.
"""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from models.webhook import JiraCommentEvent
from services.crypto import decrypt_credential
from services.hermes_client import post_comment as hermes_post_comment, put_description as hermes_put_description
from services.ticket_tracking import safe_record_transaction, safe_upsert_ticket_status

logger = logging.getLogger(__name__)

# Must match constants in routers/webhook.py
AGENT_COMMENT_PREFIX = "🤖 **Jarvis:**\n\n"

# Plain-ASCII marker embedded in every agent comment body.
AGENT_BODY_MARKER = "[jarvis-bot]"


async def detect_and_apply_approval(
    event: JiraCommentEvent,
    db: Session,
    project: Project,
    approve_subcmd: str,
) -> bool:
    """Detect a @jarvis approve <subcmd> mention and apply the stored draft.

    Routes by approve_subcmd:
    - "story description": look up PipelineState(stage='describe',
      status='awaiting_approval'), call hermes_put_description, post confirmation.
    - "architecture": reserved — returns False if no awaiting_approval row found.

    Returns True if an approval was applied, False otherwise.

    On any exception: log warning and return False.

    T-o0v-03: approve_subcmd is pre-validated by mention_parser.
    T-03-14: Single DB lookup, no retries.
    T-09-01: jira_token never logged.
    """
    # Skip comments posted by the agent itself
    if AGENT_BODY_MARKER in event.comment.body:
        return False

    subcmd = approve_subcmd.lower().strip()

    if subcmd == "story description":
        stage = "describe"
    elif subcmd == "architecture":
        stage = "architecture"
    else:
        return False

    try:
        row = (
            db.query(PipelineState)
            .filter(
                PipelineState.ticket_key == event.issue.key,
                PipelineState.stage == stage,
                PipelineState.status == "awaiting_approval",
            )
            .order_by(PipelineState.created_at.desc())
            .first()
        )

        if row is None:
            logger.debug(
                "No awaiting_approval PipelineState(stage=%s) found for ticket %s",
                stage,
                event.issue.key,
            )
            return False

        jira_token = decrypt_credential(project.jira_token)
        jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")

        await hermes_put_description(
            project.jira_url, jira_email, jira_token,
            event.issue.key, row.draft_content or ""
        )
        await hermes_post_comment(
            project.jira_url, jira_email, jira_token,
            event.issue.key,
            AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n"
            + "✅ Description updated and applied to the Jira ticket description.",
        )

        row.status = "approved"
        row.updated_at = datetime.now(tz=timezone.utc)
        db.commit()

        # Ticket-tracking bookkeeping (best-effort).
        txn_stage = "description" if stage == "describe" else "architecture"
        event_msg = (
            "Description approved and inserted to ticket"
            if stage == "describe"
            else "Architecture approved"
        )
        safe_upsert_ticket_status(
            db, project.id, event.issue.key, current_status=event_msg
        )
        safe_record_transaction(
            db, project.id, event.issue.key, txn_stage, event_msg, status="success"
        )

        logger.info(
            "Approval applied (subcmd=%r) for ticket %s (pipeline_state_id=%s)",
            subcmd,
            event.issue.key,
            row.id,
        )
        return True

    except Exception as exc:
        logger.warning(
            "detect_and_apply_approval failed for ticket %s: %s",
            event.issue.key,
            exc,
        )
        return False
