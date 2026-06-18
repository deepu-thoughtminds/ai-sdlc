"""Approval detector service for the description elaboration pipeline.

Detects approval keywords in Jira comment text and applies the approved
description to the Jira ticket description field.

Approval keywords (APPROVAL_KEYWORDS):
  A frozenset of lowercase tokens that constitute an approval signal.
  Token-based matching (not substring) prevents false positives:
    "unapproved" → False  (T-03-10: 'unapproved' is not in APPROVAL_KEYWORDS)
    "disapprove" → False  (T-03-10: 'disapprove' is not in APPROVAL_KEYWORDS)

Threat mitigations:
  T-03-10: is_approval() uses token splitting (re.split) not substring matching;
           APPROVAL_KEYWORDS is a frozenset constant, not user-configurable.
  T-03-14: detect_and_apply_approval returns False immediately when is_approval()
           fails — single pass, no retries; DB query is a single indexed lookup.
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
from services.jira_client import JiraClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Approval keyword set (T-03-10: frozenset constant, not user-configurable)
# ---------------------------------------------------------------------------

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
    """Detect an approval comment and apply the stored draft description to Jira.

    Steps:
    1. Check is_approval(comment body) — return False immediately if not an approval.
    2. Query DB for the most recent PipelineState where:
         ticket_key == event.issue.key AND stage == "describe" AND status == "awaiting_approval"
    3. If no row found: return False.
    4. Build JiraClient and call update_description(issue_key, draft_content).
    5. Set row.status = "approved"; commit.
    6. Return True.

    On any exception: log warning and return False — Jira errors must not crash the webhook.

    T-03-14: Early return on non-approval text; single DB lookup; no retries.

    Args:
        event: JiraCommentEvent with issue.key and comment.body.
        db: SQLAlchemy DB session.
        project: Project ORM object with jira_url and jira_token (encrypted).

    Returns:
        True if an approval was applied, False otherwise.
    """
    # Step 1: Early exit if comment is not an approval
    if not is_approval(event.comment.body):
        return False

    # Step 2: Query for the most recent awaiting_approval state
    try:
        row = (
            db.query(PipelineState)
            .filter(
                PipelineState.ticket_key == event.issue.key,
                PipelineState.stage == "describe",
                PipelineState.status == "awaiting_approval",
            )
            .order_by(PipelineState.created_at.desc())
            .first()
        )

        # Step 3: No pending row
        if row is None:
            logger.debug(
                "No awaiting_approval PipelineState found for ticket %s", event.issue.key
            )
            return False

        # Step 4: Build JiraClient and update the Jira ticket description
        # T-03-01: token is decrypted at runtime only; never logged
        jira_token = decrypt_credential(project.jira_token)
        jira_email = os.environ.get("JIRA_ACCOUNT_EMAIL", "")
        client = JiraClient(project.jira_url, jira_token, jira_email)
        client.update_description(event.issue.key, row.draft_content or "")

        # Step 5: Mark state as approved
        row.status = "approved"
        row.updated_at = datetime.now(tz=timezone.utc)
        db.commit()

        logger.info(
            "Approval applied for ticket %s (pipeline_state_id=%s)",
            event.issue.key,
            row.id,
        )
        # Step 6: Return True
        return True

    except Exception as exc:
        logger.warning(
            "detect_and_apply_approval failed for ticket %s: %s",
            event.issue.key,
            exc,
        )
        return False
