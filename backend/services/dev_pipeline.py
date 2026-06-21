"""Dev pipeline orchestrator — DEVPIPE-01, DEVPIPE-05.

Wires comment-history search, Confluence fetch, repo clone, code generation,
and PR creation into a single run() coroutine triggered by @jarvis start coding.

Threat mitigations:
  T-16-05: jira_token/github_token/confluence_token are NEVER passed to
           generate_code_changes — only issue metadata and content strings.
  T-16-06: Token values are NEVER logged; only issue_key and github_repo slug
           appear in log statements at INFO/WARNING level.
  T-16-07: shutil.rmtree runs in a try/finally block around clone→codegen→PR,
           preventing temp-directory accumulation on repeated failed runs.
  T-16-08: On exception the pipeline posts a Jira comment (WR-03) so failures
           are visible in the ticket without server-log access.
  T-16-09: PipelineState(status="running") is committed BEFORE asyncio.create_task
           in webhook.py — this module re-uses that row (Step 1).
"""

import logging
import os
import re
import shutil

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from services.confluence_url_finder import find_latest_architecture_url
from services.crypto import decrypt_credential
from services.code_generator import generate_code_changes
from services.graphify_service import get_codebase_summary
from services.hermes_client import (
    get_comments,
    get_confluence_page_content,
    post_comment as hermes_post_comment,
)
from services.pr_creator import apply_commit_push_and_open_pr
from services.repo_clone import clone_repository

logger = logging.getLogger(__name__)

# These constants must match architecture_pipeline.py exactly so that
# webhook.py's self-comment filter (AGENT_BODY_MARKER in event.comment.body)
# rejects agent-generated comments uniformly across all pipelines.
AGENT_COMMENT_PREFIX = "🤖 **Jarvis:**\n\n"
AGENT_BODY_MARKER = "[jarvis-bot]"


def _extract_page_id(confluence_url: str) -> str:
    """Extract the numeric Confluence page ID from a wiki URL.

    Handles URLs of the form:
      https://<host>/wiki/spaces/<space>/pages/<digits>[/...]

    Returns the digit string, or "" if no match.
    """
    match = re.search(r"/pages/(\d+)", confluence_url)
    return match.group(1) if match else ""


async def run(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    db: Session,
) -> str:
    """Run the dev pipeline end-to-end for a @jarvis start coding trigger.

    DEVPIPE-01: Searches Jira comment history for a Confluence architecture
                page URL and fetches its content.
    DEVPIPE-05: Posts the resulting GitHub PR URL as a new Jira comment.

    Graceful degradation paths (both set status="complete"):
      - No Confluence URL in comment history → informative Jira comment posted.
      - generate_code_changes returns [] → informative Jira comment posted.

    Args:
        project: Project ORM with jira_url, confluence_url, encrypted tokens.
        issue_key: Jira issue key (e.g. "PROJ-1").
        issue_summary: Issue summary field.
        issue_description: Issue description field (plain text).
        db: SQLAlchemy session for PipelineState persistence.

    Returns:
        Final comment text posted to Jira.
    """
    logger.info("Dev pipeline started for ticket %s", issue_key)

    # Step 1: Re-use the PipelineState row created by the webhook idempotency
    # guard (webhook.py creates it with status="running" BEFORE scheduling this
    # task). If no row is found (e.g. direct call in tests), create one.
    state_row = (
        db.query(PipelineState)
        .filter(
            PipelineState.ticket_key == issue_key,
            PipelineState.stage == "dev_pipeline",
            PipelineState.status == "running",
        )
        .order_by(PipelineState.id.desc())
        .first()
    )
    if state_row is None:
        state_row = PipelineState(
            project_id=project.id,
            ticket_key=issue_key,
            stage="dev_pipeline",
            status="running",
        )
        db.add(state_row)
        db.commit()

    comment_text = ""
    try:
        # Step 2: Fetch Jira comment history and search for a Confluence URL.
        jira_token = decrypt_credential(project.jira_token)
        jira_email = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
        comments = await get_comments(project.jira_url, jira_email, jira_token, issue_key)
        architecture_url = find_latest_architecture_url(comments)

        # Step 3: No Confluence URL found — post informative comment and return.
        if architecture_url is None:
            comment_text = (
                f"No Confluence architecture page was found in the comment history "
                f"for {issue_key}. Please post a Confluence architecture page URL "
                f"in the ticket comments, then retry `@jarvis start coding`."
            )
            await hermes_post_comment(
                project.jira_url,
                jira_email,
                jira_token,
                issue_key,
                AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + comment_text,
            )
            state_row.status = "complete"
            state_row.draft_content = comment_text
            db.commit()
            logger.info("Dev pipeline complete for ticket %s (no architecture URL)", issue_key)
            return comment_text

        # Step 4: Fetch the Confluence page content.
        page_id = _extract_page_id(architecture_url)
        confluence_token = decrypt_credential(project.confluence_token)
        confluence_email = getattr(project, "confluence_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
        architecture_content = await get_confluence_page_content(
            project.confluence_url, confluence_email, confluence_token, page_id
        )

        # Step 5: Build codebase context and clone the repository.
        github_token = decrypt_credential(project.github_token)
        github_repo = decrypt_credential(project.github_repo)
        github_url = getattr(project, "github_url", None) or ""
        codebase_context = get_codebase_summary(github_url, github_token)
        directory_tree = codebase_context.directory_tree if codebase_context else ""

        cloned = clone_repository(github_repo, github_token)

        # Step 6: Run codegen and PR creation in a try/finally so the temp
        # workspace is always cleaned up (T-16-07 / repo_clone.py contract).
        try:
            # Step 7: Generate code changes.
            file_changes = generate_code_changes(
                issue_key, issue_summary, issue_description, architecture_content, directory_tree
            )
            if not file_changes:
                comment_text = (
                    f"The dev pipeline ran for {issue_key} but the code generator "
                    f"produced no file changes. Please review the architecture page "
                    f"content and ensure it contains sufficient implementation detail."
                )
                await hermes_post_comment(
                    project.jira_url,
                    jira_email,
                    jira_token,
                    issue_key,
                    AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + comment_text,
                )
                state_row.status = "complete"
                state_row.draft_content = comment_text
                db.commit()
                logger.info("Dev pipeline complete for ticket %s (no code changes generated)", issue_key)
                return comment_text

            # Step 8: Commit, push, and open the PR.
            pr = apply_commit_push_and_open_pr(
                cloned.workspace_path, github_repo, github_token, issue_key, file_changes
            )
            comment_text = f"PR ready: {pr.html_url}"

        finally:
            shutil.rmtree(cloned.workspace_path, ignore_errors=True)

        # Step 9: Post the PR URL comment BEFORE finalising state (WR-01).
        await hermes_post_comment(
            project.jira_url,
            jira_email,
            jira_token,
            issue_key,
            AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + comment_text,
        )
        state_row.status = "complete"
        state_row.draft_content = comment_text
        db.commit()

    except Exception as exc:
        state_row.status = "failed"
        try:
            db.commit()
        except Exception:
            db.rollback()
        # WR-03: Notify the user in Jira so the failure is visible without
        # monitoring server logs.
        try:
            jira_token_for_notify = decrypt_credential(project.jira_token)
            jira_email_for_notify = getattr(project, "jira_email", "") or os.environ.get("JIRA_ACCOUNT_EMAIL", "")
            await hermes_post_comment(
                project.jira_url,
                jira_email_for_notify,
                jira_token_for_notify,
                issue_key,
                AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n"
                + f"Dev pipeline failed for {issue_key}: {exc}",
            )
        except Exception:
            pass
        logger.exception("Dev pipeline failed for ticket %s: %s", issue_key, exc)

    logger.info("Dev pipeline complete for ticket %s", issue_key)
    return comment_text
