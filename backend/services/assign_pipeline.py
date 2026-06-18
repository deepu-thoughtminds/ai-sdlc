"""Assign pipeline service — ASGN-01.

Handles '@hermes assign @<name>' mentions by parsing the assignee display name,
looking up their Jira account ID, assigning the ticket, and posting a confirmation.

Threat mitigations:
  T-03-11: raw_assignee = mention_result.extra.lstrip("@").strip() is passed to
           Jira /user/search as a URL query parameter (httpx URL-encodes it).
           No shell or SQL interpolation occurs.
"""

import logging
import os

from models.project import Project
from models.webhook import JiraCommentEvent
from services.crypto import decrypt_credential
from services.hermes_client import post_assign, post_comment as hermes_post_comment
from services.mention_parser import MentionResult

logger = logging.getLogger(__name__)


async def run(
    event: JiraCommentEvent,
    project: Project,
    mention_result: MentionResult,
) -> None:
    """Run the assignment pipeline for a Jira ticket.

    Steps:
    1. Extract assignee display name from mention_result.extra.
    2. Decrypt credentials.
    3. Call post_assign via hermes_client (lookup + assign in one call).
    4. If post_assign raises: post error comment via hermes_post_comment and return.
    5. Post confirmation comment via hermes_post_comment.

    T-03-11: raw_assignee passed to Jira user search API only; no SQL/shell use.

    Args:
        event: JiraCommentEvent with issue.key for the ticket to assign.
        project: Project ORM object with jira_url and encrypted jira_token.
        mention_result: MentionResult with extra field containing "@<assignee>".
    """
    issue_key = event.issue.key

    # Step 1: Extract assignee name — strip leading "@" if present
    # T-03-11: lstrip("@").strip() — bounded string operation, no injection surface
    raw_assignee = mention_result.extra.lstrip("@").strip()
    if not raw_assignee:
        logger.warning("No assignee specified in mention for ticket %s", issue_key)
        return

    # Step 2: Decrypt credentials
    # T-03-01: token decrypted at runtime; never logged
    jira_token = decrypt_credential(project.jira_token)
    jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")

    # Step 3+4+5: Lookup user, assign issue, post confirmation via hermes
    try:
        account_id = await post_assign(project.jira_url, jira_email, jira_token, issue_key, raw_assignee)
    except Exception as exc:
        logger.warning("post_assign failed for %s: %s", issue_key, exc)
        await hermes_post_comment(
            project.jira_url, jira_email, jira_token, issue_key,
            f"Could not find Jira user matching '{raw_assignee}'. Please check the display name and try again."
        )
        return

    await hermes_post_comment(
        project.jira_url, jira_email, jira_token, issue_key,
        f"Ticket {issue_key} has been assigned to {raw_assignee}."
    )

    logger.info(
        "Assigned %s to %s (account_id=%s)", issue_key, raw_assignee, account_id
    )
