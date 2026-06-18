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
  T-04-08: Architecture approval posts draft_content via JiraClient.add_comment;
           optional developer assignment via _parse_developer_from_approval + assign_pipeline.
"""

import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from models.webhook import JiraCommentEvent
from services import assign_pipeline
from services.crypto import decrypt_credential
from services.jira_client import JiraClient
from services.mention_parser import MentionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Approval keyword set (T-03-10: frozenset constant, not user-configurable)
# ---------------------------------------------------------------------------

APPROVAL_KEYWORDS: frozenset[str] = frozenset({"approved", "lgtm", "approve", "+1"})


def _parse_developer_from_approval(comment_body: str) -> str | None:
    """Extract the first @mention from an approval comment body.

    Used in the architecture approval flow to optionally assign the ticket to
    a developer named in the approval comment (e.g. 'approved @john.doe').

    Args:
        comment_body: Raw approval comment text.

    Returns:
        The first @mention name (without '@' prefix), or None if no mention found.
    """
    match = re.search(r"@([\w.\-]+)", comment_body)
    if match:
        return match.group(1)
    return None


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

    Checks both 'architecture' and 'describe' stages (priority: architecture first).

    Architecture approval flow:
    1. Check is_approval(comment body) — return False immediately if not an approval.
    2. Query DB for architecture stage row (ticket_key, stage='architecture', status='awaiting_approval').
    3. If found: post draft_content as Jira comment via JiraClient.add_comment.
    4. Set row.status = 'approved'; commit.
    5. If @developer in comment body: call assign_pipeline.run.
    6. Return True.

    Describe approval flow (fallback if no architecture row found):
    2b. Query DB for describe stage row (ticket_key, stage='describe', status='awaiting_approval').
    3b. If found: call update_description with draft_content.
    4b. Set row.status = 'approved'; commit.
    5b. Return True.

    Returns False if no approval keyword found or no matching pending row.

    On any exception: log warning and return False — Jira errors must not crash the webhook.

    T-03-14: Early return on non-approval text; single DB lookup per stage; no retries.
    T-04-08: Architecture approval posts draft_content via add_comment, not update_description.

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

    try:
        # Step 2: Check architecture stage first (priority)
        arch_row = (
            db.query(PipelineState)
            .filter(
                PipelineState.ticket_key == event.issue.key,
                PipelineState.stage == "architecture",
                PipelineState.status == "awaiting_approval",
            )
            .order_by(PipelineState.created_at.desc())
            .first()
        )

        if arch_row is not None:
            # Architecture approval: post draft_content as Jira comment
            # T-03-01: token is decrypted at runtime only; never logged
            jira_token = decrypt_credential(project.jira_token)
            jira_email = os.environ.get("JIRA_ACCOUNT_EMAIL", "")
            client = JiraClient(project.jira_url, jira_token, jira_email)
            client.add_comment(event.issue.key, arch_row.draft_content or "")

            # Mark state as approved
            arch_row.status = "approved"
            arch_row.updated_at = datetime.now(tz=timezone.utc)
            db.commit()

            logger.info(
                "Architecture approval applied for ticket %s (pipeline_state_id=%s)",
                event.issue.key,
                arch_row.id,
            )

            # Optional: assign developer if @mention found in comment
            developer = _parse_developer_from_approval(event.comment.body)
            if developer:
                mention_result = MentionResult(
                    mention_target="hermes",
                    stage="assign",
                    extra=f"@{developer}",
                )
                await assign_pipeline.run(event, project, mention_result)

            return True

        # Step 2b: Fallback — check describe stage
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
        jira_email = os.environ.get("JIRA_ACCOUNT_EMAIL", "")
        client = JiraClient(project.jira_url, jira_token, jira_email)
        client.update_description(event.issue.key, desc_row.draft_content or "")

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
