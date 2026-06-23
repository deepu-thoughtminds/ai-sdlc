"""QA pipeline orchestrator — TESTEXEC-01, TESTEXEC-02, AUTOFIX-04.

Wires repository cloning, toolchain detection, static analysis execution,
workspace cleanup, and Jira comment posting into a single async run()
coroutine. Mirrors merge_pipeline.py structure exactly.

Phase 23 scope: static analysis only (ruff/mypy/bandit/eslint/tsc).
Phase 24 will add LLM-generated unit tests.
Phase 25 will add the auto-fix loop (AUTOFIX-04 bounded retry, T-23-05).
Phase 26 will add the @jarvis run qa trigger and auto-chain after merge.

Threat mitigations:
  T-23-01: All subprocess.run() calls inside test_executor.py use list-form
           args — shell=True is NEVER used anywhere in the QA pipeline.
  T-23-02: subprocess.TimeoutExpired caught per-command in test_executor;
           timed_out=True set; loop continues — pipeline never hangs.
  T-23-03: shutil.rmtree(cloned.workspace_path, ignore_errors=True) runs
           in a finally block unconditionally — temp dirs never accumulate.
  T-23-04: state_row.qa_attempt is set to 0 and committed to DB BEFORE any
           execution begins. If the process crashes mid-run, qa_attempt=0
           in DB prevents a phantom restart from treating the run as if it
           never started.
  T-23-05: (Phase 25) Auto-fix loop bounded at 3 attempts; same-error
           repeat detected for early termination (non-progress detection).
"""

import logging
import os
import shutil

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from services.crypto import decrypt_credential
from services.hermes_client import post_comment as hermes_post_comment
from services.repo_clone import clone_repository
from services.test_executor import TestResult, run_static_analysis

logger = logging.getLogger(__name__)

# Must match constants in architecture_pipeline.py / merge_pipeline.py so that
# webhook.py's self-comment filter (AGENT_BODY_MARKER in event.comment.body)
# rejects agent-generated comments uniformly across all pipelines.
AGENT_COMMENT_PREFIX = "\U0001f916 **Jarvis:**\n\n"
AGENT_BODY_MARKER = "[jarvis-bot]"


async def run(
    project: Project,
    issue_key: str,
    issue_summary: str,
    issue_description: str,
    db: Session,
) -> str:
    """Run the QA pipeline for a single Jira issue.

    TESTEXEC-01: Clone a fresh workspace; auto-detect project toolchain.
    TESTEXEC-02: Execute each tool via Docker subprocess with hard timeout.
    T-23-03: Always clean up temporary workspace in finally block.
    T-23-04: Commit qa_attempt=0 before any execution begins.

    Args:
        project:           Project ORM row with encrypted credentials.
        issue_key:         Jira issue key (e.g. "PROJ-1").
        issue_summary:     Issue summary (passed for future Phase 24 use).
        issue_description: Issue description (passed for future Phase 24 use).
        db:                SQLAlchemy session — must be a fresh SessionLocal()
                           from the background closure, not a request-scoped
                           session (mirrors T-17-08 / T-16-09 convention).

    Returns:
        The final comment text posted to Jira.
    """
    logger.info("QA pipeline started for ticket %s", issue_key)
    comment_text = ""

    # Step 1 — Re-use or create a PipelineState row (stage="qa").
    # Mirrors merge_pipeline.py / dev_pipeline.py Step 1 convention:
    # webhook.py creates the row (status="running") before scheduling the
    # task; run() re-uses that row. If no row found (e.g. direct test call),
    # create one.
    state_row = (
        db.query(PipelineState)
        .filter(
            PipelineState.ticket_key == issue_key,
            PipelineState.stage == "qa",
            PipelineState.status == "running",
        )
        .order_by(PipelineState.id.desc())
        .first()
    )

    if state_row is None:
        state_row = PipelineState(
            project_id=project.id,
            ticket_key=issue_key,
            stage="qa",
            status="running",
        )
        db.add(state_row)
        db.commit()

    # T-23-04: Commit qa_attempt=0 BEFORE any execution begins.
    state_row.qa_attempt = 0
    db.commit()

    cloned = None
    # Bug fix (post-execution review): jira_token/jira_email must be bound
    # BEFORE the try block. Step 6 (Jira comment posting) runs unconditionally
    # after the try/except/finally below and references both names. If
    # decrypt_credential(project.github_token) raised before jira_token was
    # assigned, Step 6 would raise NameError instead of gracefully posting
    # the failure comment — masking the real pipeline failure entirely.
    jira_token = ""
    jira_email = getattr(project, "jira_email", "") or os.environ.get(
        "JIRA_ACCOUNT_EMAIL", ""
    )
    try:
        # Step 3 — Decrypt credentials.
        # T-23-01: decrypted values are passed as function arguments only;
        # never interpolated into comment text, f-strings, or log statements.
        github_token = decrypt_credential(project.github_token)
        github_repo = decrypt_credential(project.github_repo)
        jira_token = decrypt_credential(project.jira_token)

        # Step 4 — Clone a fresh workspace (TESTEXEC-02: never reuse dev workspace).
        cloned = clone_repository(github_repo, github_token)

        # Step 5 — Run static analysis tools via Docker subprocess.
        results = run_static_analysis(cloned.workspace_path)

        comment_text = _format_static_analysis_comment(results, issue_key)

        # Mark pipeline complete on success.
        state_row.status = "complete"
        state_row.draft_content = comment_text
        db.commit()

    except Exception as exc:
        state_row.status = "failed"
        db.commit()
        logger.exception("QA pipeline failed for ticket %s: %s", issue_key, exc)
        comment_text = (
            f"QA pipeline failed for {issue_key}.\n\n"
            f"Error: {type(exc).__name__} — {exc}"
        )

    finally:
        # T-23-03: Always clean up the temporary workspace, regardless of
        # whether execution succeeded or failed.
        if cloned is not None:
            shutil.rmtree(cloned.workspace_path, ignore_errors=True)

    # Step 6 — Post Jira comment. Wrapped in its own try/except so a comment
    # failure does not mask the pipeline outcome.
    try:
        await hermes_post_comment(
            project.jira_url,
            jira_email,
            jira_token,
            issue_key,
            AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER + "\n\n" + comment_text,
        )
    except Exception as comment_exc:
        logger.warning(
            "QA pipeline: failed to post Jira comment for %s: %s",
            issue_key,
            comment_exc,
        )

    logger.info("QA pipeline complete for ticket %s", issue_key)
    return comment_text


def _format_static_analysis_comment(results: list[TestResult], issue_key: str) -> str:
    """Format static analysis results into a human-readable Jira comment.

    Truncates per-tool stderr output to 500 characters to avoid enormous
    comments. Phase 24 will add structured reporting via QAREP-01.

    Args:
        results:   List of TestResult objects from run_static_analysis().
        issue_key: Jira issue key (included in the comment header).

    Returns:
        Multi-line string suitable for posting as a Jira comment body.
    """
    if not results:
        return (
            f"QA static analysis for {issue_key}: no tools detected.\n\n"
            "No pyproject.toml, setup.cfg, or package.json found in repository."
        )

    lines = [f"QA static analysis for {issue_key}:\n"]
    for r in results:
        if r.returncode == 0:
            lines.append(f"- {r.tool}: PASSED")
        elif r.timed_out:
            lines.append(f"- {r.tool}: TIMED OUT (120s)")
        else:
            stderr_snippet = r.stderr[:500] if r.stderr else ""
            lines.append(
                f"- {r.tool}: FAILED (exit {r.returncode})\n{stderr_snippet}"
            )

    return "\n".join(lines)
