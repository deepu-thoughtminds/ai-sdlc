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
  - @jarvis merge pr → idempotency guard (returns duplicate_pipeline if active)
    → merge_pipeline (background task) → PipelineState running → complete
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
import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException
from pymongo.database import Database

from database import get_db, get_database
from models.webhook import JiraCommentEvent, JiraIssueCreatedEvent
from repositories import pipeline_state_repo, projects_repo
from services import approval_detector, architecture_pipeline, assign_pipeline, describe_pipeline, dev_pipeline, merge_pipeline, qa_pipeline
from services.crypto import decrypt_credential
from services.hermes_client import post_comment as hermes_post_comment
from services.llm_router import route_request
from services.mention_parser import parse_mention
from services.ticket_tracking import safe_record_transaction, safe_upsert_ticket_status

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

    WR-01 fix: uses hmac.compare_digest for constant-time comparison to
    prevent timing-based secret inference attacks.

    If JIRA_WEBHOOK_SECRET is not configured (e.g. dev/test without the env
    var), the check is skipped so the service remains usable without secrets.
    """
    expected_secret = os.environ.get("JIRA_WEBHOOK_SECRET")
    if not expected_secret:
        # No secret configured — allow through (useful in local/test envs)
        return
    # WR-01 fix: constant-time comparison via hmac.compare_digest prevents
    # timing attacks where an attacker infers characters by measuring response times.
    if x_jira_webhook_secret is None or not hmac.compare_digest(
        x_jira_webhook_secret, expected_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")


@router.post("/jira-comment")
async def handle_jira_comment(
    event: JiraCommentEvent,
    _secret: None = Depends(verify_webhook_secret),
    db: Database = Depends(get_db),
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
    project = projects_repo.get_by_key(db, project_key)

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

    # Step 4a: Handle 'describe' action
    if mention_result is not None and mention_result.action == "describe":
        # Expire any previous awaiting_approval describe states for this ticket
        # so stale states from earlier failed runs don't get processed later.
        pipeline_state_repo.update_status_many(
            db,
            {
                "ticket_key": event.issue.key,
                "stage": "describe",
                "status": "awaiting_approval",
            },
            "superseded",
        )

        # Create initial PipelineState row with status="processing"
        state_row = pipeline_state_repo.create(
            db, project.id, event.issue.key, "describe", status="processing"
        )

        # Run the describe pipeline (async — awaited directly)
        description = await describe_pipeline.run(event, project, db)

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
        pipeline_state_repo.update(
            db, state_row.id, status="awaiting_approval", draft_content=description
        )

        # Ticket-tracking bookkeeping (best-effort).
        safe_upsert_ticket_status(
            db,
            project.id,
            event.issue.key,
            pipeline_stage="description",
            current_status="Generated description, awaiting approval",
            summary=getattr(event.issue, "summary", None),
            issue_type=getattr(event.issue, "issue_type", None),
        )
        safe_record_transaction(
            db,
            project.id,
            event.issue.key,
            "description",
            "Generated description, awaiting approval",
            status="success",
        )

        logger.info(
            "Describe pipeline complete for issue %s — awaiting approval",
            event.issue.key,
        )
        return {"status": "received", "action": "describe", "ticket": event.issue.key}

    # Step 4b: Handle 'architecture' action (background task — LLM call is heavy)
    elif mention_result is not None and mention_result.action == "architecture":
        # T-13-04 / ARCHINT-02: Idempotency guard — if an active (running)
        # PipelineState row already exists for this ticket+stage, return 200
        # immediately without scheduling a second heavy LLM task.
        # "complete" and "failed" states allow re-triggering so users can rerun
        # after a ticket changes substantially or a previous run failed.
        existing = pipeline_state_repo.find_latest(
            db, ticket_key=event.issue.key, stage="architecture", statuses=["running"]
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
        state_row = pipeline_state_repo.create(
            db, project.id, event.issue.key, "architecture", status="running"
        )

        issue_summary = event.issue.summary
        issue_description = getattr(event.issue, "description", "") or ""
        # Capture only primitive values (project_id, strings); the background
        # coroutine grabs its own Database handle via get_database().
        project_id = project.id

        async def _run_architecture_background() -> None:
            bg_db = get_database()
            bg_project = projects_repo.get(bg_db, project_id)
            # CR-03 fix: guard against project being deleted between webhook
            # receipt and background task execution.
            if bg_project is None:
                logger.error(
                    "Project id=%s not found in background task for issue %s — aborting architecture",
                    project_id, event.issue.key,
                )
                return
            await architecture_pipeline.run(
                bg_project, event.issue.key, issue_summary, issue_description, bg_db
            )

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

    # Step 4c: Handle 'assign' action
    # ASGN-02: @jarvis assign @developer-name (architect → dev)
    # ASGN-03: @jarvis assign @qa-name (developer → QA)
    # Both are satisfied by the existing stage-agnostic assign_pipeline.run() below.
    elif mention_result is not None and mention_result.action == "assign":
        await assign_pipeline.run(event, project, mention_result)
        logger.info("Assign pipeline complete for issue %s", event.issue.key)
        return {"status": "received", "action": "assign", "ticket": event.issue.key}

    # Step 4d: Handle 'approve' action — mention-based approval (@jarvis approve <subcmd>)
    # T-o0v-03: sub-command is from LLM entities or extra text; unknown intents return None.
    elif mention_result is not None and mention_result.action == "approve":
        approve_subcmd = mention_result.entities.get("target", mention_result.extra).lower().strip()
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

    # Step 4e: Handle 'start_coding' action (background task — codegen/PR is heavy)
    elif mention_result is not None and mention_result.action == "start_coding":
        # T-16-09: Idempotency guard — same pattern as the architecture branch
        # above. "complete" and "failed" states allow re-triggering.
        existing = pipeline_state_repo.find_latest(
            db, ticket_key=event.issue.key, stage="dev_pipeline", statuses=["running"]
        )
        if existing is not None:
            logger.info(
                "Dev pipeline already active for issue %s (state_id=%s) — ignoring duplicate",
                event.issue.key,
                existing.id,
            )
            return {"status": "received", "action": "ignored", "reason": "duplicate_pipeline"}

        # Create PipelineState row with status="running" BEFORE scheduling the
        # background task so the idempotency guard above can detect a near-
        # simultaneous second webhook. dev_pipeline.run() re-uses this row.
        state_row = pipeline_state_repo.create(
            db, project.id, event.issue.key, "dev_pipeline", status="running"
        )

        issue_summary = event.issue.summary
        issue_description = getattr(event.issue, "description", "") or ""
        project_id = project.id

        async def _run_dev_pipeline_background() -> None:
            bg_db = get_database()
            bg_project = projects_repo.get(bg_db, project_id)
            # CR-03 fix: guard against project being deleted between webhook
            # receipt and background task execution.
            if bg_project is None:
                logger.error(
                    "Project id=%s not found in background task for issue %s — aborting dev_pipeline",
                    project_id, event.issue.key,
                )
                return
            await dev_pipeline.run(
                bg_project, event.issue.key, issue_summary, issue_description, bg_db
            )

        asyncio.create_task(_run_dev_pipeline_background())
        logger.info(
            "Dev pipeline scheduled for issue %s (state_id=%s)",
            event.issue.key,
            state_row.id,
        )
        return {
            "status": "received",
            "action": "start_coding",
            "routed_to": "dev_pipeline",
        }

    # Step 4f: Handle 'merge_pr' action (background task — GitHub API merge is heavy)
    # T-17-06: Idempotency guard — same pattern as architecture/start_coding branches.
    # PipelineState(status="running") is created and committed BEFORE asyncio.create_task
    # so that a near-simultaneous duplicate webhook is blocked before a second merge
    # attempt can be scheduled. "complete" and "failed" states allow re-triggering.
    elif mention_result is not None and mention_result.action == "merge_pr":
        existing = pipeline_state_repo.find_latest(
            db, ticket_key=event.issue.key, stage="merge_pr", statuses=["running"]
        )
        if existing is not None:
            logger.info(
                "Merge pipeline already active for issue %s (state_id=%s) — ignoring duplicate",
                event.issue.key,
                existing.id,
            )
            return {"status": "received", "action": "ignored", "reason": "duplicate_pipeline"}

        # Create PipelineState row with status="running" BEFORE scheduling the
        # background task so the idempotency guard above can detect a near-
        # simultaneous second webhook. merge_pipeline.run() re-uses this row.
        state_row = pipeline_state_repo.create(
            db, project.id, event.issue.key, "merge_pr", status="running"
        )

        issue_summary = event.issue.summary
        issue_description = getattr(event.issue, "description", "") or ""
        project_id = project.id

        async def _run_merge_background() -> None:
            bg_db = get_database()
            bg_project = projects_repo.get(bg_db, project_id)
            # CR-03 fix: guard against project being deleted between webhook
            # receipt and background task execution. Without this check,
            # bg_project=None causes AttributeError in merge_pipeline.run()
            # and leaves PipelineState stuck at status="running".
            if bg_project is None:
                logger.error(
                    "Project id=%s not found in background task for issue %s — aborting merge",
                    project_id, event.issue.key,
                )
                return
            await merge_pipeline.run(
                bg_project, event.issue.key, issue_summary, issue_description, bg_db
            )

        asyncio.create_task(_run_merge_background())
        logger.info(
            "Merge pipeline scheduled for issue %s (state_id=%s)",
            event.issue.key,
            state_row.id,
        )
        return {
            "status": "received",
            "action": "merge_pr",
            "routed_to": "merge_pipeline",
        }

    # Step 4f2: Handle 'run_qa' action (background task — QA sandbox run is heavy)
    # QATRIG-02: Idempotency guard uses the SAME shared has_active_qa_run() guard
    # (QATRIG-03) that merge_pipeline.py's auto-chain hook (QATRIG-01) checks.
    elif mention_result is not None and mention_result.action == "run_qa":
        if qa_pipeline.has_active_qa_run(event.issue.key, db):
            logger.info(
                "QA pipeline already active for issue %s — ignoring duplicate",
                event.issue.key,
            )
            return {"status": "received", "action": "ignored", "reason": "duplicate_pipeline"}

        state_row = pipeline_state_repo.create(
            db, project.id, event.issue.key, "qa", status="running"
        )

        issue_summary = event.issue.summary
        issue_description = getattr(event.issue, "description", "") or ""
        project_id = project.id

        async def _run_qa_background() -> None:
            bg_db = get_database()
            bg_project = projects_repo.get(bg_db, project_id)
            if bg_project is None:
                logger.error(
                    "Project id=%s not found in background task for issue %s — aborting run_qa",
                    project_id, event.issue.key,
                )
                return
            await qa_pipeline.run(
                bg_project, event.issue.key, issue_summary, issue_description, bg_db
            )

        asyncio.create_task(_run_qa_background())
        logger.info(
            "QA pipeline scheduled for issue %s (state_id=%s)",
            event.issue.key,
            state_row.id,
        )
        return {
            "status": "received",
            "action": "run_qa",
            "routed_to": "qa_pipeline",
        }

    # Step 4g: No recognized mention.
    # If @jarvis appears in the body but intent is unrecognized, post a help comment
    # (INTENT-02). If there's no @jarvis at all, return the ignored response silently.
    elif mention_result is None:
        if "@jarvis" in event.comment.body.lower():
            _help_body = (
                AGENT_COMMENT_PREFIX
                + AGENT_BODY_MARKER + "\n\n"
                + "I didn't understand that command. Try one of:\n\n"
                + "- `@jarvis describe` — elaborate the ticket description\n"
                + "- `@jarvis architecture` — generate architecture diagram\n"
                + "- `@jarvis start coding` — begin implementation\n"
                + "- `@jarvis merge pr` — merge the open PR\n"
                + "- `@jarvis assign @name` — assign the ticket to someone\n"
                + "- `@jarvis approve story description` — apply the draft description\n"
                + "- `@jarvis approve architecture` — proceed with the architecture\n"
            )
            try:
                jira_token = decrypt_credential(project.jira_token)
                jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
                await hermes_post_comment(
                    project.jira_url,
                    jira_email,
                    jira_token,
                    event.issue.key,
                    _help_body,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to post help comment for ticket %s: %s", event.issue.key, exc
                )
            logger.info("Issue %s: unrecognized @jarvis intent — help comment posted", event.issue.key)
            return {"status": "received", "action": "intent_unknown", "reason": "help_comment_posted"}
        return {"status": "received", "action": "ignored"}

    # Step 4h: Other actions (codegen, testgen — future phases)
    else:
        route_result = route_request(mention_result.action, event.comment.body)
        logger.info(
            "Issue %s: action=%s routed to %s",
            event.issue.key,
            mention_result.action,
            route_result.provider,
        )
        return {
            "status": "received",
            "action": mention_result.action,
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
    db: Database = Depends(get_db),
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
    project = projects_repo.get_by_key(db, project_key)

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
    existing = pipeline_state_repo.find_latest(
        db,
        ticket_key=event.issue.key,
        stage="describe",
        statuses=["processing", "awaiting_approval", "approved"],
    )
    if existing is not None:
        logger.info(
            "Describe pipeline already active for issue %s (state_id=%s) — ignoring duplicate",
            event.issue.key,
            existing.id,
        )
        return {"status": "received", "action": "ignored", "reason": "duplicate_pipeline"}

    # Step 5: Expire any previous superseded describe states
    pipeline_state_repo.update_status_many(
        db,
        {
            "ticket_key": event.issue.key,
            "stage": "describe",
            "status": "awaiting_approval",
        },
        "superseded",
    )

    # Step 6: Create initial PipelineState row with status='processing'
    state_row = pipeline_state_repo.create(
        db, project.id, event.issue.key, "describe", status="processing"
    )

    # Ticket-tracking bookkeeping: record the ticket's creation (best-effort).
    safe_upsert_ticket_status(
        db,
        project.id,
        event.issue.key,
        pipeline_stage="description",
        current_status="Ticket created",
        summary=event.issue.summary,
        issue_type=event.issue.issue_type,
    )
    safe_record_transaction(
        db,
        project.id,
        event.issue.key,
        "description",
        "Ticket created",
        status="in_progress",
    )

    # Step 7: Run describe pipeline via adapter (no comment body on issue_created)
    adapter = _IssueCreatedAdapter(issue=event.issue, comment=_NullComment())
    description = await describe_pipeline.run(adapter, project, db)

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
    pipeline_state_repo.update(
        db, state_row.id, status="awaiting_approval", draft_content=description
    )

    safe_upsert_ticket_status(
        db,
        project.id,
        event.issue.key,
        current_status="Generated description, awaiting approval",
    )
    safe_record_transaction(
        db,
        project.id,
        event.issue.key,
        "description",
        "Generated description, awaiting approval",
        status="success",
    )

    logger.info(
        "Auto-describe pipeline complete for issue %s (issue_created) — awaiting approval",
        event.issue.key,
    )
    return {"status": "received", "action": "describe", "ticket": event.issue.key}
