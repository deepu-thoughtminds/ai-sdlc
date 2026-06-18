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
from services.jira_client import JiraClient
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
    2. Build JiraClient with decrypted token.
    3. Lookup user account_id via JiraClient.lookup_user.
    4. If not found: post error comment and return.
    5. Call assign_issue to reassign the ticket.
    6. Post confirmation comment.

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

    # Step 2: Build JiraClient
    # T-03-01: token decrypted at runtime; never logged
    jira_token = decrypt_credential(project.jira_token)
    jira_email = os.environ.get("JIRA_ACCOUNT_EMAIL", "")
    client = JiraClient(project.jira_url, jira_token, jira_email)

    # Step 3: Lookup user account_id
    account_id = client.lookup_user(raw_assignee)

    # Step 4: Handle user not found
    if account_id is None:
        logger.warning(
            "Jira user '%s' not found for ticket %s", raw_assignee, issue_key
        )
        client.add_comment(
            issue_key,
            f"Could not find Jira user matching '{raw_assignee}'. "
            "Please check the display name and try again.",
        )
        return

    # Step 5: Assign the issue
    client.assign_issue(issue_key, account_id)

    # Step 6: Post confirmation comment
    client.add_comment(
        issue_key,
        f"Ticket {issue_key} has been assigned to {raw_assignee}.",
    )

    logger.info(
        "Assigned %s to %s (account_id=%s)", issue_key, raw_assignee, account_id
    )
