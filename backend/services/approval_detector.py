"""Approval detector service for the description elaboration pipeline.

Detects approval keywords in Jira comment text and applies the approved
description to the Jira ticket description field.

Approval keywords (APPROVAL_KEYWORDS):
  A frozenset of lowercase tokens that constitute an approval signal.
  Token-based matching (not substring) prevents false positives:
    "unapproved" → False  (T-03-10: 'unapproved' is not in APPROVAL_KEYWORDS)
    "disapprove" → False  (T-03-10: 'disapprove' is not in APPROVAL_KEYWORDS)

Scope: describe stage only.
  The architecture approval path was removed in Phase 13-02. After Plan 01 rewrote
  the architecture pipeline to run single-pass (status lifecycle: running → complete),
  the architecture stage never reaches status='awaiting_approval', making the approval
  block dead code. The dead code and its helpers are removed here.

Threat mitigations:
  T-03-10: is_approval() uses token splitting (re.split) not substring matching;
           APPROVAL_KEYWORDS is a frozenset constant, not user-configurable.
  T-03-14: detect_and_apply_approval returns False immediately when is_approval()
           fails — single pass, no retries; DB query is a single indexed lookup.
  T-09-01: jira_token never logged; only issue_key logged at INFO via hermes_client.
"""

import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from models.webhook import JiraCommentEvent
from services.crypto import decrypt_credential
from services.hermes_client import post_comment as hermes_post_comment, put_description as hermes_put_description

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Approval keyword set (T-03-10: frozenset constant, not user-configurable)
# ---------------------------------------------------------------------------

# Must match constants in routers/webhook.py
AGENT_COMMENT_PREFIX = "🤖 **Jarvis:**\n\n"

# Plain-ASCII marker embedded in every agent comment body.
# Jira reformats markdown (ADF) before delivering webhooks, so emoji/bold prefix
# matching via startswith() is unreliable. This ASCII token survives ADF round-trips.
AGENT_BODY_MARKER = "[jarvis-bot]"

APPROVAL_KEYWORDS: frozenset[str] = frozenset({"approved", "lgtm", "approve", "+1"})



def is_approval(text: str) -> bool:
    """Return True if the text contains an approval keyword as a standalone token.

    Tokenizes by splitting on whitespace and punctuation characters (except '+').
    This ensures "unapproved" does not match "approved" (T-03-10).

    Args:
        text: Raw comment text to check.

    Returns:
        True if any token exactly matches an APPROVAL_KEYWORD, False otherwise.
    """
    # Split on whitespace and common punctuation; keep '+' so "+1" is preserved
    tokens = set(re.split(r"[\s,;.!?/\\()\[\]{}\"']+", text.lower()))
    # Remove empty strings from split
    tokens.discard("")
    return bool(tokens & APPROVAL_KEYWORDS)


async def detect_and_apply_approval(
    event: JiraCommentEvent,
    db: Session,
    project: Project,
) -> bool:
    """Detect an approval comment and apply the stored draft to Jira.

    Describe approval flow:
    1. Check is_approval(comment body) — return False immediately if not an approval.
    2. Query DB for describe stage row (ticket_key, stage='describe', status='awaiting_approval').
    3. If found: call hermes_put_description with draft_content; post confirmation comment.
    4. Set row.status = 'approved'; commit.
    5. Return True.

    Returns False if no approval keyword found or no matching pending describe row.

    On any exception: log warning and return False — Jira errors must not crash the webhook.

    T-03-14: Early return on non-approval text; single DB lookup; no retries.

    Note: The architecture approval path was removed in Phase 13-02. The architecture
    pipeline now completes directly to status='complete' (never awaiting_approval), so
    the architecture approval block was dead code after Plan 01's rewrite.

    Args:
        event: JiraCommentEvent with issue.key and comment.body.
        db: SQLAlchemy DB session.
        project: Project ORM object with jira_url and jira_token (encrypted).

    Returns:
        True if an approval was applied, False otherwise.
    """
    # Skip any comment posted by the agent itself (defense-in-depth).
    # AGENT_BODY_MARKER is a plain-ASCII token that survives Jira's ADF markdown
    # reformatting, unlike AGENT_COMMENT_PREFIX which uses emoji/bold markup.
    if AGENT_BODY_MARKER in event.comment.body:
        return False

    # Step 1: Early exit if comment is not an approval
    if not is_approval(event.comment.body):
        return False

    try:
        # Step 2: Check describe stage
        desc_row = (
            db.query(PipelineState)
            .filter(
                PipelineState.ticket_key == event.issue.key,
                PipelineState.stage == "describe",
                PipelineState.status == "awaiting_approval",
            )
            .order_by(PipelineState.created_at.desc())
            .first()
        )

        if desc_row is None:
            logger.debug(
                "No awaiting_approval PipelineState found for ticket %s", event.issue.key
            )
            return False

        # Describe approval: update Jira ticket description field
        # T-03-01: token is decrypted at runtime only; never logged
        jira_token = decrypt_credential(project.jira_token)
        jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
        await hermes_put_description(project.jira_url, jira_email, jira_token, event.issue.key, desc_row.draft_content or "")
        await hermes_post_comment(project.jira_url, jira_email, jira_token, event.issue.key, AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + "✅ Description updated and applied to the Jira ticket description.")

        # Mark state as approved
        desc_row.status = "approved"
        desc_row.updated_at = datetime.now(tz=timezone.utc)
        db.commit()

        logger.info(
            "Describe approval applied for ticket %s (pipeline_state_id=%s)",
            event.issue.key,
            desc_row.id,
        )
        return True

    except Exception as exc:
        logger.warning(
            "detect_and_apply_approval failed for ticket %s: %s",
            event.issue.key,
            exc,
        )
        return False
