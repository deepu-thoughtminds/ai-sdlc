"""Webhook router for Jira comment and issue events.

Receives POST requests from Jira Cloud, validates the webhook secret header,
and orchestrates the full SDLC pipeline:

  /webhook/jira-issue (jira:issue_created events):
  - Story created → describe_pipeline auto-trigger → post draft comment
    → PipelineState(stage='describe', status='awaiting_approval')
  - Non-Story or unknown project → ignored

  /webhook/jira-comment (comment_created / comment_updated events):
  - @jarvis describe → legacy path (auto-trigger via /jira-issue is now primary)
    → describe_pipeline → post draft comment → PipelineState awaiting_approval
  - @jarvis architecture → idempotency guard (returns duplicate_pipeline if active)
    → architecture_pipeline (background task) → PipelineState running → complete
  - @jarvis assign @<name> → assign_pipeline → lookup_user + assign_issue + confirmation
    ASGN-02: @jarvis assign @developer-name (architect → dev)
    ASGN-03: @jarvis assign @qa-name (developer → QA)
    Both are satisfied by the existing stage-agnostic assign_pipeline.run() above.
  - @jarvis approve story description → approval_detector (story description approval)
  - @jarvis approve architecture → approval_detector (architecture approval)
  - No mention / unknown mention → ignored (no keyword-based approvals any more)

Threat mitigations applied:
- T-02-01 / T-o0v-01: JIRA_WEBHOOK_SECRET header validation — returns 401 on mismatch;
  applied to both /jira-comment and /jira-issue routes.
- T-02-04: comment.body max_length enforced at the Pydantic model layer
  (JiraComment.body = Field(..., max_length=10000)).
- T-03-13: project_key extracted by rsplit('-', 1)[0] — bounded string op;
           queried via SQLAlchemy parameterized query (no SQL injection surface).
- T-o0v-03: approve sub-command validated against APPROVE_SUBCMDS frozenset in
  mention_parser; unknown sub-commands return None (ignored before reaching this router).
- T-o0v-04: idempotency guard on /jira-issue: existing processing/awaiting_approval
  PipelineState blocks duplicate describe pipeline for same ticket.
"""

import asyncio
import dataclasses
import datetime
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from models.pipeline_state import PipelineState
from models.project import Project
from models.webhook import JiraCommentEvent, JiraIssueCreatedEvent
from services import approval_detector, architecture_pipeline, assign_pipeline, describe_pipeline
from services.crypto import decrypt_credential
from services.hermes_client import post_comment as hermes_post_comment
from services.llm_router import route_request
from services.mention_parser import parse_mention

logger = logging.getLogger(__name__)

# Prefix applied to all agent-generated Jira comments.
AGENT_COMMENT_PREFIX = "🤖 **Jarvis:**\n\n"

# Plain-ASCII marker embedded in every agent comment body.
# Used to identify agent-generated comments in webhook payloads — more reliable
# than AGENT_COMMENT_PREFIX because Jira reformats markdown (ADF conversion)
# before delivering the webhook, so startswith() on emoji/bold markup is fragile.
AGENT_BODY_MARKER = "[jarvis-bot]"

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
    4. Parse @jarvis mention from comment body.
    5a. stage == "describe": run describe_pipeline, post draft comment, save PipelineState.
    5b. stage == "architecture": idempotency guard checks for active run; if none, creates PipelineState(status=running) then schedules architecture_pipeline as asyncio background task.
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

    # Ignore comments posted by the agent itself — prevents self-triggering loops.
    # Use AGENT_BODY_MARKER (plain ASCII) instead of startswith(AGENT_COMMENT_PREFIX)
    # because Jira reformats markdown via ADF before delivering the webhook body,
    # making emoji/bold prefix matching unreliable.
    if AGENT_BODY_MARKER in event.comment.body:
        return {"status": "received", "action": "ignored", "reason": "agent_comment"}

    # Step 3: Parse the mention
    mention_result = parse_mention(event.comment.body)

    # Step 4a: Handle 'describe' stage
    if mention_result is not None and mention_result.stage == "describe":
        # Expire any previous awaiting_approval describe states for this ticket
        # so stale states from earlier failed runs don't get processed later.
        db.query(PipelineState).filter(
            PipelineState.ticket_key == event.issue.key,
            PipelineState.stage == "describe",
            PipelineState.status == "awaiting_approval",
        ).update({"status": "superseded"})
        db.flush()

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
                AGENT_COMMENT_PREFIX
                + AGENT_BODY_MARKER + "\n\n"
                + "*Draft description — reply* `@jarvis approve story description` *to apply it to the ticket:*\n\n"
                + description,
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
        # T-13-04 / ARCHINT-02: Idempotency guard — if an active (running)
        # PipelineState row already exists for this ticket+stage, return 200
        # immediately without scheduling a second heavy LLM task.
        # "complete" and "failed" states allow re-triggering so users can rerun
        # after a ticket changes substantially or a previous run failed.
        existing = (
            db.query(PipelineState)
            .filter(
                PipelineState.ticket_key == event.issue.key,
                PipelineState.stage == "architecture",
                PipelineState.status.in_(["running"]),
            )
            .first()
        )
        if existing is not None:
            logger.info(
                "Architecture pipeline already active for issue %s (state_id=%s) — ignoring duplicate",
                event.issue.key,
                existing.id,
            )
            return {"status": "received", "action": "ignored", "reason": "duplicate_pipeline"}

        # Create PipelineState row with status="running" BEFORE scheduling the
        # background task so the idempotency guard above can detect a near-
        # simultaneous second webhook. The architecture_pipeline.run() will
        # re-use this row instead of creating a second one.
        state_row = PipelineState(
            project_id=project.id,
            ticket_key=event.issue.key,
            stage="architecture",
            status="running",
        )
        db.add(state_row)
        db.commit()

        issue_summary = event.issue.summary
        issue_description = getattr(event.issue, "description", "") or ""
        # CR-02: Do NOT pass the request-scoped `db` session to the background task.
        # FastAPI closes the session when the handler returns (via get_db's finally block),
        # so the background task would receive an already-closed session. Instead, capture
        # only primitive values (project_id, strings) and open a fresh SessionLocal()
        # inside the background coroutine.
        project_id = project.id

        async def _run_architecture_background() -> None:
            bg_db = SessionLocal()
            try:
                bg_project = bg_db.query(Project).filter(Project.id == project_id).first()
                await architecture_pipeline.run(
                    bg_project, event.issue.key, issue_summary, issue_description, bg_db
                )
            finally:
                bg_db.close()

        asyncio.create_task(_run_architecture_background())
        logger.info(
            "Architecture pipeline scheduled for issue %s (state_id=%s)",
            event.issue.key,
            state_row.id,
        )
        return {
            "status": "received",
            "action": "architecture",
            "routed_to": "freellmapi",
        }

    # Step 4c: Handle 'assign' stage
    # ASGN-02: @jarvis assign @developer-name (architect → dev)
    # ASGN-03: @jarvis assign @qa-name (developer → QA)
    # Both are satisfied by the existing stage-agnostic assign_pipeline.run() below.
    elif mention_result is not None and mention_result.stage == "assign":
        await assign_pipeline.run(event, project, mention_result)
        logger.info("Assign pipeline complete for issue %s", event.issue.key)
        return {"status": "received", "action": "assign", "ticket": event.issue.key}

    # Step 4d: Handle 'approve' stage — mention-based approval (@jarvis approve <subcmd>)
    # T-o0v-03: sub-command already validated against APPROVE_SUBCMDS in mention_parser;
    # unknown sub-commands return None and never reach this branch.
    elif mention_result is not None and mention_result.stage == "approve":
        approve_subcmd = mention_result.extra.lower().strip()
        applied = await approval_detector.detect_and_apply_approval(
            event, db, project, approve_subcmd
        )
        if applied:
            return {
                "status": "received",
                "action": "approval_applied",
                "ticket": event.issue.key,
            }
        return {"status": "received", "action": "ignored", "reason": "no_pending_approval"}

    # Step 4e: No recognized mention — ignored (keyword-based approvals removed;
    # approval now requires explicit @jarvis approve <subcmd> mention)
    elif mention_result is None:
        return {"status": "received", "action": "ignored"}

    # Step 4f: Other stages (codegen, testgen — future phases)
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


# ---------------------------------------------------------------------------
# Adapter for JiraIssueCreatedEvent → describe_pipeline compatibility
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class _NullComment:
    """Stub comment with empty body — used to satisfy describe_pipeline.run's
    duck-typed 'event.comment.body' access when called from issue_created path.
    No @jarvis trigger text is available at creation time; the prompt uses
    event.issue.summary and event.issue.description instead.
    """
    body: str = ""


@dataclasses.dataclass
class _IssueCreatedAdapter:
    """Adapts a JiraIssueCreatedEvent to the duck-typed interface expected by
    describe_pipeline.run (which accesses event.issue.key, event.issue.summary,
    and event.comment.body).
    """
    issue: object
    comment: object = dataclasses.field(default_factory=_NullComment)


@router.post("/jira-issue")
async def handle_jira_issue_created(
    event: JiraIssueCreatedEvent,
    _secret: None = Depends(verify_webhook_secret),
    db: Session = Depends(get_db),
) -> dict:
    """Receive a Jira issue_created webhook event and auto-trigger describe pipeline.

    Handles jira:issue_created events for Story issue types. On story creation,
    automatically runs describe_pipeline and posts a draft comment asking for
    @jarvis approve story description.

    Routing logic:
    1. Extract project_key from issue.key.
    2. Look up project in DB — ignore if not found.
    3. Ignore if issue_type is not 'Story' (case-insensitive).
    4. Idempotency guard: ignore if a PipelineState(stage='describe',
       status in ['processing', 'awaiting_approval']) already exists.
    5. Expire any previous superseded describe states.
    6. Create PipelineState(stage='describe', status='processing').
    7. Run describe_pipeline via _IssueCreatedAdapter (no comment body available).
    8. Post draft comment with @jarvis approve story description instruction.
    9. Update PipelineState to status='awaiting_approval'.

    Threat mitigations:
    - T-o0v-01: Same verify_webhook_secret dependency as /jira-comment (401 on mismatch).
    - T-o0v-02: issue_type validated case-insensitively against "story" — extracted via
      safe .get() in JiraIssue._flatten_fields (never eval'd).
    - T-o0v-04: Idempotency guard prevents duplicate describe pipelines.
    """
    logger.debug("Issue-created webhook received: %s", event.issue.key)

    # Step 1+2: Identify the project from the issue key
    project_key = event.issue.key.rsplit("-", 1)[0]
    project = db.query(Project).filter(Project.project_key == project_key).first()

    if project is None:
        logger.warning(
            "No project found for project_key=%s (issue %s) — ignoring issue_created webhook",
            project_key,
            event.issue.key,
        )
        return {"status": "received", "action": "ignored", "reason": "project_not_found"}

    # Step 3: Only auto-describe Story issue types (T-o0v-02)
    if event.issue.issue_type.lower() != "story":
        logger.debug(
            "Issue %s is type %r, not a Story — ignoring issue_created webhook",
            event.issue.key,
            event.issue.issue_type,
        )
        return {"status": "received", "action": "ignored", "reason": "not_a_story"}

    # Step 4: Idempotency guard — T-o0v-04
    existing = (
        db.query(PipelineState)
        .filter(
            PipelineState.ticket_key == event.issue.key,
            PipelineState.stage == "describe",
            PipelineState.status.in_(["processing", "awaiting_approval"]),
        )
        .first()
    )
    if existing is not None:
        logger.info(
            "Describe pipeline already active for issue %s (state_id=%s) — ignoring duplicate",
            event.issue.key,
            existing.id,
        )
        return {"status": "received", "action": "ignored", "reason": "duplicate_pipeline"}

    # Step 5: Expire any previous superseded describe states
    db.query(PipelineState).filter(
        PipelineState.ticket_key == event.issue.key,
        PipelineState.stage == "describe",
        PipelineState.status == "awaiting_approval",
    ).update({"status": "superseded"})
    db.flush()

    # Step 6: Create initial PipelineState row with status='processing'
    state_row = PipelineState(
        project_id=project.id,
        ticket_key=event.issue.key,
        stage="describe",
        status="processing",
    )
    db.add(state_row)
    db.commit()
    db.refresh(state_row)

    # Step 7: Run describe pipeline via adapter (no comment body on issue_created)
    adapter = _IssueCreatedAdapter(issue=event.issue, comment=_NullComment())
    description = await describe_pipeline.run(adapter, project)

    # Step 8: Post draft comment with @jarvis approve story description instruction
    try:
        jira_token = decrypt_credential(project.jira_token)
        jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
        await hermes_post_comment(
            project.jira_url,
            jira_email,
            jira_token,
            event.issue.key,
            AGENT_COMMENT_PREFIX
            + AGENT_BODY_MARKER + "\n\n"
            + "*Draft description — reply* `@jarvis approve story description` *to apply it to the ticket:*\n\n"
            + description,
        )
    except Exception as exc:
        logger.warning(
            "Failed to post draft comment for ticket %s: %s", event.issue.key, exc
        )

    # Step 9: Update PipelineState to awaiting_approval with the draft content
    state_row.status = "awaiting_approval"
    state_row.draft_content = description
    state_row.updated_at = datetime.datetime.now(tz=datetime.timezone.utc)
    db.commit()

    logger.info(
        "Auto-describe pipeline complete for issue %s (issue_created) — awaiting approval",
        event.issue.key,
    )
    return {"status": "received", "action": "describe", "ticket": event.issue.key}
