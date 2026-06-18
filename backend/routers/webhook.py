"""Webhook router for Jira comment events.

Receives POST /webhook/jira-comment from Jira Cloud, validates the webhook
secret header, parses @hermes mentions, and routes heavy/light tasks to the
appropriate LLM provider.

Threat mitigations applied:
- T-02-01: JIRA_WEBHOOK_SECRET header validation — returns 401 on mismatch.
- T-02-04: comment.body max_length enforced at the Pydantic model layer
  (JiraComment.body = Field(..., max_length=10000)).
"""

import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException

from models.webhook import JiraCommentEvent
from services.llm_router import route_request
from services.mention_parser import parse_mention

logger = logging.getLogger(__name__)

router = APIRouter()


def verify_webhook_secret(
    x_jira_webhook_secret: str | None = Header(default=None),
) -> None:
    """FastAPI dependency: validate the X-Jira-Webhook-Secret header.

    Reads JIRA_WEBHOOK_SECRET from env. If the env var is set, the header
    must be present and must match exactly. Returns 401 on mismatch.

    If JIRA_WEBHOOK_SECRET is not configured (e.g. dev/test without the env
    var), the check is skipped so the service remains usable without secrets.
    """
    expected_secret = os.environ.get("JIRA_WEBHOOK_SECRET")
    if not expected_secret:
        # No secret configured — allow through (useful in local/test envs)
        return
    if x_jira_webhook_secret is None or x_jira_webhook_secret != expected_secret:
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")


@router.post("/jira-comment")
async def handle_jira_comment(
    event: JiraCommentEvent,
    _secret: None = Depends(verify_webhook_secret),
) -> dict:
    """Receive a Jira comment webhook event, parse the mention, and route to LLM.

    Returns:
        {"status": "received", "action": "ignored"} — if no @hermes mention found.
        {"status": "received", "action": <stage>, "routed_to": <provider>} — on mention.
    """
    logger.debug("Webhook received: %s", event.issue.key)

    mention_result = parse_mention(event.comment.body)

    if mention_result is None:
        return {"status": "received", "action": "ignored"}

    route_result = route_request(mention_result.stage, event.comment.body)
    logger.info(
        "Issue %s: stage=%s routed to %s",
        event.issue.key,
        mention_result.stage,
        route_result.provider,
    )

    return {
        "status": "received",
        "action": mention_result.stage,
        "routed_to": route_result.provider,
    }
