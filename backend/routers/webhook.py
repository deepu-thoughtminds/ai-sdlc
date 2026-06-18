"""Webhook router for Jira comment events.

Receives POST /webhook/jira-comment from Jira Cloud, validates the webhook
secret header, and orchestrates the full SDLC pipeline:
  - @hermes describe → describe_pipeline → post draft comment → PipelineState awaiting_approval
  - @hermes architecture → architecture_pipeline (background task) → PipelineState awaiting_approval
  - @hermes assign @<name> → assign_pipeline → lookup_user + assign_issue + confirmation
    ASGN-02: @hermes assign @developer-name (architect → dev)
    ASGN-03: @hermes assign @qa-name (developer → QA)
    Both are satisfied by the existing stage-agnostic assign_pipeline.run() above.
  - Plain comment with approval keyword → approval_detector → update Jira description / post arch comment

Threat mitigations applied:
- T-02-01: JIRA_WEBHOOK_SECRET header validation — returns 401 on mismatch.
- T-02-04: comment.body max_length enforced at the Pydantic model layer
  (JiraComment.body = Field(..., max_length=10000)).
- T-03-13: project_key extracted by rsplit('-', 1)[0] — bounded string op;
           queried via SQLAlchemy parameterized query (no SQL injection surface).
"""

import asyncio
import datetime
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models.pipeline_state import PipelineState
from models.project import Project
from models.webhook import JiraCommentEvent
from services import approval_detector, architecture_pipeline, assign_pipeline, describe_pipeline
from services.crypto import decrypt_credential
from services.hermes_client import post_comment as hermes_post_comment
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
    db: Session = Depends(get_db),
) -> dict:
    """Receive a Jira comment webhook event and orchestrate the pipeline.

    Routing logic:
    1. Parse project_key from the issue key (e.g. "PROJ-1" → "PROJ").
    2. Look up the project in the DB by project_key.
    3. If no project: return {"status": "received", "action": "ignored", "reason": "project_not_found"}.
    4. Parse @hermes mention from comment body.
    5a. stage == "describe": run describe_pipeline, post draft comment, save PipelineState.
    5b. stage == "architecture": schedule architecture_pipeline as asyncio background task.
    5c. stage == "assign": run assign_pipeline (ASGN-02 + ASGN-03 — stage-agnostic).
    5d. No mention: check for approval keyword; call approval_detector.
    5e. Other known stages: route via llm_router (for future phases / backward compat).

    T-03-13: project_key parsing uses rsplit("-", 1) — bounded, safe operation.
    """
    logger.debug("Webhook received: %s", event.issue.key)

    # Step 1+2: Identify the project from the issue key
    # T-03-13: rsplit("-", 1)[0] is a bounded string operation; no injection surface
    project_key = event.issue.key.rsplit("-", 1)[0]
    project = db.query(Project).filter(Project.project_key == project_key).first()

    if project is None:
        logger.warning(
            "No project found for project_key=%s (issue %s) — ignoring webhook",
            project_key,
            event.issue.key,
        )
        return {"status": "received", "action": "ignored", "reason": "project_not_found"}

    # Step 3: Parse the mention
    mention_result = parse_mention(event.comment.body)

    # Step 4a: Handle 'describe' stage
    if mention_result is not None and mention_result.stage == "describe":
        # Create initial PipelineState row with status="processing"
        state_row = PipelineState(
            project_id=project.id,
            ticket_key=event.issue.key,
            stage="describe",
            status="processing",
        )
        db.add(state_row)
        db.commit()
        db.refresh(state_row)

        # Run the describe pipeline (async — awaited directly)
        description = await describe_pipeline.run(event, project)

        # Post the draft as a Jira comment
        try:
            jira_token = decrypt_credential(project.jira_token)
            jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
            await hermes_post_comment(
                project.jira_url,
                jira_email,
                jira_token,
                event.issue.key,
                (
                    "*Draft description (awaiting your approval):*\n\n"
                    f"{description}\n\n"
                    "Reply with 'approved', 'LGTM', or '+1' to apply this description to the ticket."
                ),
            )
        except Exception as exc:
            logger.warning(
                "Failed to post draft comment for ticket %s: %s", event.issue.key, exc
            )

        # Update PipelineState to awaiting_approval with the draft content
        state_row.status = "awaiting_approval"
        state_row.draft_content = description
        state_row.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
        db.commit()

        logger.info(
            "Describe pipeline complete for issue %s — awaiting approval",
            event.issue.key,
        )
        return {"status": "received", "action": "describe", "ticket": event.issue.key}

    # Step 4b: Handle 'architecture' stage (background task — LLM call is heavy)
    elif mention_result is not None and mention_result.stage == "architecture":
        issue_summary = event.issue.summary
        issue_description = getattr(event.issue, "description", "") or ""
        asyncio.create_task(
            architecture_pipeline.run(
                project, event.issue.key, issue_summary, issue_description, db
            )
        )
        logger.info(
            "Architecture pipeline scheduled for issue %s", event.issue.key
        )
        return {
            "status": "received",
            "action": "architecture",
            "routed_to": "freellmapi",
        }

    # Step 4c: Handle 'assign' stage
    # ASGN-02: @hermes assign @developer-name (architect → dev)
    # ASGN-03: @hermes assign @qa-name (developer → QA)
    # Both are satisfied by the existing stage-agnostic assign_pipeline.run() below.
    elif mention_result is not None and mention_result.stage == "assign":
        await assign_pipeline.run(event, project, mention_result)
        logger.info("Assign pipeline complete for issue %s", event.issue.key)
        return {"status": "received", "action": "assign", "ticket": event.issue.key}

    # Step 4d: No recognized mention — check for approval keyword
    elif mention_result is None:
        applied = await approval_detector.detect_and_apply_approval(event, db, project)
        if applied:
            return {
                "status": "received",
                "action": "approval_applied",
                "ticket": event.issue.key,
            }
        return {"status": "received", "action": "ignored"}

    # Step 4e: Other stages (codegen, testgen — future phases)
    # Keep llm_router routing for backward compatibility with existing tests
    else:
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
