"""Merge pipeline orchestrator — PRMERGE-01, PRMERGE-02.

Wires PR discovery (pr_creator.find_and_merge_pr), Jira status transition
(hermes_client.update_status), and confirmation-comment posting into a single
async run() coroutine triggered by @jarvis merge pr.

Threat mitigations:
  T-17-05: github_token and jira_token are decrypted locally and passed ONLY
           as function arguments to find_and_merge_pr / update_status / hermes_post_comment.
           They are NEVER interpolated into comment_text, f-strings in comment bodies,
           or logger calls. Only issue_key, PR metadata, and the merge commit SHA
           appear in any user-visible or log output.
  T-17-06: PipelineState(stage="merge_pr", status="running") is created and committed
           by webhook.py BEFORE asyncio.create_task schedules this coroutine.
           run() re-uses that existing row (query → fallback-create if absent from
           direct call), mirroring the T-16-09/architecture_pipeline Step 1 convention.
           This ensures the idempotency guard in webhook.py detects near-simultaneous
           duplicate webhooks before a second run() could be scheduled.
  T-17-07: find_and_merge_pr returning None is a normal control-flow branch (no open PR
           found). The pipeline posts an informative Jira comment and sets
           PipelineState.status="complete" — not "failed". An informative no-op is not
           a pipeline failure.
  T-17-08: This module receives a fresh SessionLocal() session opened by the background
           closure _run_merge_background() in webhook.py — never the request-scoped db
           (CR-02 session-boundary safety).
"""

import logging
import os

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from services import codebase_scan_service
from services.crypto import decrypt_credential
from services.hermes_client import (
    post_comment as hermes_post_comment,
    update_status,
)
from services.pr_creator import find_and_merge_pr

logger = logging.getLogger(__name__)

# These constants must match webhook.py and dev_pipeline.py exactly so that
# the webhook self-comment filter (AGENT_BODY_MARKER in event.comment.body)
# rejects agent-generated comments uniformly across all pipelines.
AGENT_COMMENT_PREFIX = "🤖 **Jarvis:**\n\n"
AGENT_BODY_MARKER = "[jarvis-bot]"


async def run(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    db: Session,
) -> str:
    """Run the merge pipeline end-to-end for a @jarvis merge pr trigger.

    PRMERGE-01: Finds and merges the open PR for the ticket via the GitHub API.
    PRMERGE-02: Posts the merge commit SHA and PR URL as a Jira comment; updates
                the Jira story status to "Done" (best-effort — update_status
                failure does not block the confirmation comment).

    Graceful degradation paths (both set status="complete"):
      - No open PR found → informative Jira comment posted explaining what was
        searched (branch jarvis/issue-{key} and title containing {key}).
      - update_status returns False → SHA confirmation comment still posted;
        status set to "complete" not "failed".

    Args:
        project:          Project ORM with encrypted jira_token, github_token,
                          github_repo, and jira_url attributes.
        issue_key:        Jira issue key (e.g. "PROJ-1").
        issue_summary:    Issue summary field (unused by merge path, kept for
                          consistent signature across pipelines).
        issue_description: Issue description field (unused, kept for symmetry).
        db:               SQLAlchemy session (fresh SessionLocal() from background
                          closure — never the request-scoped session).

    Returns:
        Final comment text posted to Jira (or "" if exception path was taken).
    """
    logger.info("Merge pipeline started for ticket %s", issue_key)

    # Step 1: Re-use the PipelineState row created by the webhook idempotency
    # guard (webhook.py creates it with status="running" BEFORE scheduling this
    # task). If no row is found (e.g. direct call in tests), create one.
    state_row = (
        db.query(PipelineState)
        .filter(
            PipelineState.ticket_key == issue_key,
            PipelineState.stage == "merge_pr",
            PipelineState.status == "running",
        )
        .order_by(PipelineState.id.desc())
        .first()
    )
    if state_row is None:
        state_row = PipelineState(
            project_id=project.id,
            ticket_key=issue_key,
            stage="merge_pr",
            status="running",
        )
        db.add(state_row)
        db.commit()

    comment_text = ""
    try:
        # Step 2: Decrypt credentials and call find_and_merge_pr.
        # T-17-05: tokens passed only as function args — never interpolated into
        # comment bodies or log statements.
        github_token = decrypt_credential(project.github_token)
        github_repo = decrypt_credential(project.github_repo)

        # find_and_merge_pr is a synchronous httpx function (matching
        # apply_commit_push_and_open_pr's sync convention in pr_creator.py).
        merge_result = find_and_merge_pr(github_repo, github_token, issue_key)

        # Step 3: No open PR found — post informative comment and return cleanly.
        # T-17-07: This is NOT an error condition — set status="complete" not "failed".
        if merge_result is None:
            comment_text = (
                f"No open PR was found for {issue_key}. "
                f"Searched for branch `jarvis/issue-{issue_key}` and PR titles "
                f"containing `{issue_key}`. If a PR exists, ensure it is open and "
                f"that the branch name or title matches the expected patterns, "
                f"then retry `@jarvis merge pr`."
            )
            await hermes_post_comment(
                project.jira_url,
                getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", ""),
                decrypt_credential(project.jira_token),
                issue_key,
                AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + comment_text,
            )
            state_row.status = "complete"
            state_row.draft_content = comment_text
            db.commit()
            logger.info(
                "Merge pipeline complete for ticket %s (no open PR found)", issue_key
            )
            return comment_text

        # CR-04 fix: verify that the GitHub API actually merged the PR.
        # A 200 response with merged=False is possible in edge cases (e.g.
        # some GitHub Enterprise configurations or race conditions). Without
        # this check the pipeline would post a false "PR merged" confirmation.
        if not merge_result.merged:
            raise RuntimeError(
                f"GitHub reported PR #{merge_result.pr_number} was not merged "
                f"(merged=False in API response)"
            )

        # Step 4: PR found and merged — decrypt Jira credentials for status update.
        jira_token = decrypt_credential(project.jira_token)
        jira_email = (
            getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
        )

        # Step 5: Transition Jira story status to "Done" (best-effort — T-17-09).
        # update_status returns False on failure but never raises; a False return
        # must not block the SHA confirmation comment (Test 3 / graceful degradation).
        status_updated = await update_status(
            project.jira_url, jira_email, jira_token, issue_key, "Done"
        )
        if not status_updated:
            logger.warning(
                "Merge pipeline: Jira status update to 'Done' failed for %s — "
                "continuing with SHA confirmation comment",
                issue_key,
            )

        # Step 6: Build and post SHA confirmation comment BEFORE finalising state
        # (WR-01 — post before marking complete so the Jira comment is visible
        # even if the state-commit below fails).
        # T-17-05: only merge_result.sha, merge_result.pr_url, and issue_key are
        # interpolated — no token values.
        comment_text = (
            f"PR #{merge_result.pr_number} merged for {issue_key}.\n\n"
            f"Merge commit SHA: `{merge_result.sha}`\n"
            f"PR URL: {merge_result.pr_url}"
        )
        await hermes_post_comment(
            project.jira_url,
            jira_email,
            jira_token,
            issue_key,
            AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + comment_text,
        )

        # Post-merge re-scan hook (SNAPSHOT-01): refresh .hermes/codebase.md on main.
        # Isolated in its own try/except — a scan failure must NEVER affect
        # state_row.status, the posted Jira comment, or db.commit() of Step 7.
        # T-19-01: exception text logged server-side only; never interpolated into
        #          comment_text or any value passed to hermes_post_comment.
        # T-19-03: RuntimeError from codebase_scan_service (e.g. GitHub API timeout)
        #          is caught here; the merge outcome is unaffected.
        try:
            await codebase_scan_service.run(github_repo, github_token, project.id, db)
            logger.info(
                "Codebase snapshot refresh triggered after merge for project id=%d",
                project.id,
            )
        except Exception as scan_exc:
            logger.warning(
                "Post-merge codebase snapshot refresh failed for project id=%d: %s"
                " — merge still succeeded",
                project.id,
                scan_exc,
            )

        # Step 7: Finalise state row.
        state_row.status = "complete"
        state_row.draft_content = comment_text
        db.commit()

    except Exception as exc:
        state_row.status = "failed"
        try:
            db.commit()
        except Exception:
            db.rollback()

        # WR-02 fix: Do not interpolate the exception message into the Jira
        # comment. The raw exception string may contain internal URLs, stack
        # details, or credential-adjacent data from httpx transport errors.
        # Log the full exception server-side for debugging; show only a generic
        # message to Jira viewers.
        try:
            notify_token = decrypt_credential(project.jira_token)
            notify_email = (
                getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
            )
            failure_body = (
                f"Merge pipeline failed for {issue_key}. "
                f"Check server logs for details."
            )
            await hermes_post_comment(
                project.jira_url,
                notify_email,
                notify_token,
                issue_key,
                AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + failure_body,
            )
        except Exception:
            pass
        logger.exception("Merge pipeline failed for ticket %s: %s", issue_key, exc)

    logger.info("Merge pipeline complete for ticket %s", issue_key)
    return comment_text
