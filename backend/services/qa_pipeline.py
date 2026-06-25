"""QA pipeline orchestrator — TESTEXEC-01, TESTEXEC-02, AUTOFIX-04.

Wires repository cloning, LLM-driven unit test generation, toolchain detection,
static analysis execution, sandboxed unit test execution, workspace cleanup,
and Jira comment posting into a single async run() coroutine.
Mirrors merge_pipeline.py structure exactly.

Phase 23 scope: static analysis only (ruff/mypy/bandit/eslint/tsc).
Phase 24 scope: LLM-generated unit tests + combined per-category Jira comment
  (TESTGEN-01: generate_unit_tests via freellmapi testgen stage;
   QAREP-01: Unit Tests + Static Analysis sections in single comment).
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
  T-24-01: FileChange.path is resolved against workspace_root and rejected
           (ValueError, caught per-file and skipped) if it escapes the
           workspace — mirrors pr_creator.py's T-15-06 guard exactly,
           preventing the LLM from writing outside the cloned repo.
  T-24-02: generate_unit_tests() receives only issue_key/summary/description/
           codebase_context/relevant_file_contents — no token or credential
           values are ever forwarded into the test-generation prompt.
"""

import glob
import logging
import os
import pathlib
import shutil

from sqlalchemy.orm import Session

from models.pipeline_state import PipelineState
from models.project import Project
from services.auto_fix_loop import MAX_ATTEMPTS as MAX_AUTOFIX_ATTEMPTS
from services.auto_fix_loop import run_auto_fix_loop
from services.codebase_snapshot_reader import get_codebase_snapshot
from services.confluence_client import publish_qa_report
from services.crypto import decrypt_credential
from services.hermes_client import post_comment as hermes_post_comment
from services.repo_clone import clone_repository
from services.test_executor import TestResult, ToolchainCommand, run_command, run_static_analysis
from services.test_generator import generate_e2e_tests, generate_unit_tests

logger = logging.getLogger(__name__)

# Must match constants in architecture_pipeline.py / merge_pipeline.py so that
# webhook.py's self-comment filter (AGENT_BODY_MARKER in event.comment.body)
# rejects agent-generated comments uniformly across all pipelines.
AGENT_COMMENT_PREFIX = "\U0001f916 **Jarvis:**\n\n"
AGENT_BODY_MARKER = "[jarvis-bot]"

# Caps for relevant_file_contents collection (T-24-04: bound prompt size)
_MAX_SOURCE_FILES = 20
_MAX_FILE_CHARS = 50_000

# Extensions to include when collecting relevant source files
_SOURCE_EXTENSIONS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".rb", ".rs",
    ".c", ".cpp", ".h", ".hpp", ".cs",
}


def has_active_qa_run(ticket_key: str, db: Session) -> bool:
    """Return True when a QA PipelineState with status='running' exists for ticket_key.

    QATRIG-03: Shared idempotency guard used by both merge_pipeline.py auto-chain
    (QATRIG-01) and the @jarvis run qa webhook branch (QATRIG-02) to prevent
    simultaneous duplicate QA runs for the same ticket.
    """
    return (
        db.query(PipelineState)
        .filter(
            PipelineState.ticket_key == ticket_key,
            PipelineState.stage == "qa",
            PipelineState.status == "running",
        )
        .first()
        is not None
    )


def _collect_relevant_files(workspace_path: str) -> dict[str, str]:
    """Walk the cloned workspace and collect source file contents.

    T-24-04: Caps at _MAX_SOURCE_FILES files and _MAX_FILE_CHARS chars per file
    to prevent oversized prompts. Skips binary files and files exceeding the
    per-file size cap. Returns a mapping of relative path → content.

    Args:
        workspace_path: Absolute path to the cloned repository workspace.

    Returns:
        Dict mapping relative file path → text content (capped).
    """
    collected: dict[str, str] = {}
    ws_root = pathlib.Path(workspace_path)

    try:
        for entry in ws_root.rglob("*"):
            if len(collected) >= _MAX_SOURCE_FILES:
                break
            if entry.is_symlink() or not entry.is_file():
                continue
            if entry.suffix.lower() not in _SOURCE_EXTENSIONS:
                continue
            # Skip hidden dirs / .git internals
            parts = entry.relative_to(ws_root).parts
            if any(p.startswith(".") for p in parts):
                continue

            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue

            if len(text) > _MAX_FILE_CHARS:
                logger.debug("Skipping large file %s (%d chars)", entry, len(text))
                continue

            rel_path = str(entry.relative_to(ws_root))
            collected[rel_path] = text

    except Exception as exc:
        logger.warning("Error collecting source files from workspace: %s", exc)

    return collected


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
    TESTGEN-01: Generate grounded pytest unit tests via freellmapi.
    QAREP-01: Post single Jira comment with Unit Tests + Static Analysis sections.
    T-23-03: Always clean up temporary workspace in finally block.
    T-23-04: Commit qa_attempt=0 before any execution begins.
    T-24-01: Path-traversal guard for generated test files (mirrors T-15-06).
    T-24-02: No credentials forwarded into generate_unit_tests().

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
    unit_test_results: list[TestResult] = []

    try:
        # Step 3 — Decrypt credentials.
        # T-23-01: decrypted values are passed as function arguments only;
        # never interpolated into comment text, f-strings, or log statements.
        github_token = decrypt_credential(project.github_token)
        github_repo = decrypt_credential(project.github_repo)
        jira_token = decrypt_credential(project.jira_token)

        # Step 4 — Clone a fresh workspace (TESTEXEC-02: never reuse dev workspace).
        cloned = clone_repository(github_repo, github_token)

        # Step 4b — Generate and execute LLM-driven unit tests (TESTGEN-01).
        # T-24-02: codebase_context and file contents only; no credentials forwarded.

        # (a) Fetch codebase snapshot context (.hermes/codebase.md)
        codebase_context = await get_codebase_snapshot(github_repo, github_token)

        # (b) Collect relevant source files from the cloned workspace (T-24-04: bounded)
        relevant_file_contents = _collect_relevant_files(cloned.workspace_path)

        # (c) Generate unit tests via freellmapi
        file_changes = generate_unit_tests(
            issue_key=issue_key,
            issue_summary=issue_summary,
            issue_description=issue_description,
            codebase_context=codebase_context,
            relevant_file_contents=relevant_file_contents,
        )

        # (d) Write each generated file with path-traversal guard (T-24-01)
        workspace_root = pathlib.Path(cloned.workspace_path).resolve()
        for change in file_changes:
            try:
                resolved = (workspace_root / change.path).resolve()
                # T-24-01: Reject any path escaping the workspace root
                if not str(resolved).startswith(str(workspace_root) + "/"):
                    raise ValueError(
                        f"FileChange path escapes workspace: '{change.path}' "
                        f"resolves to '{resolved}'"
                    )
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_text(change.content, encoding="utf-8")
                logger.info("Wrote generated test file: %s", change.path)

                # (e) Execute the generated test file via run_command —
                # dispatch by extension (TESTGEN-04): pytest for .py, the
                # repo's own `npm test` for .test.ts(x)/.spec.ts(x) so
                # whatever JS runner the repo already uses (vitest/jest)
                # actually applies, instead of always shelling to pytest.
                image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
                if change.path.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                    cmd = ToolchainCommand(
                        name="npm test",
                        command=[
                            "docker", "run", "--rm",
                            "-v", f"{cloned.workspace_path}:/workspace",
                            "-w", "/workspace",
                            image,
                            "sh", "-c",
                            f"npm ci --silent && npm test -- {change.path}",
                        ],
                    )
                    result = run_command(cmd, timeout=300)
                else:
                    cmd = ToolchainCommand(
                        name="pytest",
                        command=[
                            "docker", "run", "--rm",
                            "-v", f"{cloned.workspace_path}:/workspace",
                            image,
                            "pytest", f"/workspace/{change.path}", "-v",
                        ],
                    )
                    result = run_command(cmd)
                result.file_path = change.path  # for auto_fix_loop re-run dispatch
                unit_test_results.append(result)
                logger.info(
                    "Generated test %s exit=%d timed_out=%s",
                    change.path,
                    result.returncode,
                    result.timed_out,
                )

            except ValueError as ve:
                # T-24-01: Per-file catch — log, skip, continue with remaining files
                logger.warning(
                    "Skipping generated test file due to path-traversal violation: %s", ve
                )
                continue

        # (f) empty file_changes: unit_test_results stays [] — no execution

        # Step 4c — Bounded auto-fix loop on unit test failure (AUTOFIX-01/02/03).
        autofix_pr_url: str | None = None
        if any(r.returncode != 0 and not r.timed_out for r in unit_test_results):
            unit_test_results, autofix_pr_url = run_auto_fix_loop(
                unit_test_results,
                cloned.workspace_path,
                issue_key,
                github_repo,
                github_token,
                state_row,
                db,
            )

        # Step 4d — Playwright E2E tests (TESTGEN-03).
        # T-26-02: Only generate/run E2E tests when a Playwright config is present.
        e2e_results: list[TestResult] = []
        playwright_configs = glob.glob(
            os.path.join(cloned.workspace_path, "playwright.config.*")
        )
        if not playwright_configs:
            logger.info("No playwright.config.* found in workspace — skipping E2E generation")
            e2e_skip_note: str | None = "E2E tests skipped (no playwright.config.* detected in repository)."
        else:
            e2e_skip_note = None
            e2e_file_changes = generate_e2e_tests(
                issue_key=issue_key,
                issue_summary=issue_summary,
                issue_description=issue_description,
                codebase_context=codebase_context,
                relevant_file_contents=relevant_file_contents,
            )
            for change in e2e_file_changes:
                try:
                    resolved = (workspace_root / change.path).resolve()
                    # T-26-01: Reject any path escaping the workspace root
                    if not str(resolved).startswith(str(workspace_root) + "/"):
                        raise ValueError(
                            f"E2E FileChange path escapes workspace: '{change.path}' "
                            f"resolves to '{resolved}'"
                        )
                    resolved.parent.mkdir(parents=True, exist_ok=True)
                    resolved.write_text(change.content, encoding="utf-8")
                    logger.info("Wrote generated E2E test file: %s", change.path)

                    image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
                    cmd = ToolchainCommand(
                        name="playwright",
                        command=[
                            "docker", "run", "--rm",
                            "-v", f"{cloned.workspace_path}:/workspace",
                            image,
                            "npx", "playwright", "test", f"/workspace/{change.path}",
                        ],
                    )
                    result = run_command(cmd)
                    e2e_results.append(result)
                    logger.info(
                        "E2E test %s exit=%d timed_out=%s",
                        change.path,
                        result.returncode,
                        result.timed_out,
                    )
                except ValueError as ve:
                    logger.warning(
                        "Skipping generated E2E file due to path-traversal violation: %s", ve
                    )
                    continue

        # Step 5 — Run static analysis tools via Docker subprocess.
        # JS tools run npm ci first, so 300s timeout (vs default 120s).
        static_results = run_static_analysis(cloned.workspace_path, timeout=300)

        comment_text = _format_qa_comment(unit_test_results, e2e_results, static_results, issue_key, e2e_skip_note)
        still_failing = any(r.returncode != 0 and not r.timed_out for r in unit_test_results)
        if autofix_pr_url and still_failing:
            comment_text += (
                f"\n\nAuto-fix exhausted {MAX_AUTOFIX_ATTEMPTS} attempts — "
                f"see PR for partial fixes: {autofix_pr_url}"
            )
        elif autofix_pr_url:
            comment_text += f"\n\nAuto-fix PR: {autofix_pr_url}"
        elif still_failing:
            comment_text += "\n\nAuto-fix could not generate a fix."

        # Mark pipeline complete on success.
        state_row.status = "complete"
        state_row.draft_content = comment_text
        db.commit()

    except Exception as exc:
        state_row.status = "failed"
        try:
            db.commit()
        except Exception:
            db.rollback()
        logger.exception("QA pipeline failed for ticket %s: %s", issue_key, exc)
        comment_text = (
            f"QA pipeline failed for {issue_key}. "
            "Check server logs for details."
        )

    finally:
        # T-23-03: Always clean up the temporary workspace, regardless of
        # whether execution succeeded or failed.
        if cloned is not None:
            shutil.rmtree(cloned.workspace_path, ignore_errors=True)

    # Step 5.5 — Publish a brief QA report to Confluence (graceful degradation
    # on failure — same pattern as architecture_pipeline's publish_architecture).
    try:
        qa_page_url = await publish_qa_report(project, issue_key, comment_text)
    except Exception as conf_exc:
        logger.warning(
            "QA pipeline: Confluence publish failed for %s: %s", issue_key, conf_exc
        )
        qa_page_url = ""
    if qa_page_url:
        comment_text += f"\n\nFull report: {qa_page_url}"

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


def _format_qa_comment(
    unit_test_results: list[TestResult],
    e2e_results: list[TestResult],
    static_results: list[TestResult],
    issue_key: str,
    e2e_skip_note: str | None = None,
) -> str:
    """Format QA results into a human-readable Jira comment with per-category sections.

    QAREP-01: Renders two labeled sections — "Unit Tests" and "Static Analysis" —
    satisfying the per-category minimum requirement.

    Truncates per-tool stderr output to 500 characters to avoid enormous comments
    (T-24-05: truncation mirrors existing static-analysis output behaviour).

    Args:
        unit_test_results: List of TestResult from executing generated pytest file(s).
                           Empty list when no unit tests were generated.
        static_results:    List of TestResult from run_static_analysis().
        issue_key:         Jira issue key (included in the comment header).

    Returns:
        Multi-line string suitable for posting as a Jira comment body.
    """
    lines = [f"QA results for {issue_key}:\n"]

    # --- Unit Tests section ---
    lines.append("**Unit Tests:**")
    if not unit_test_results:
        lines.append("- No unit tests were generated (LLM returned no test files).")
    else:
        for r in unit_test_results:
            if r.returncode == 0:
                lines.append(f"- {r.tool}: PASSED")
            elif r.timed_out:
                timeout_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(f"- {r.tool}: TIMED OUT ({timeout_snippet})")
            else:
                stderr_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(
                    f"- {r.tool}: FAILED (exit {r.returncode})\n{stderr_snippet}"
                )

    lines.append("")  # blank line between sections

    # --- E2E Tests section ---
    lines.append("**E2E Tests:**")
    if e2e_skip_note:
        lines.append(f"- {e2e_skip_note}")
    elif not e2e_results:
        lines.append("- No E2E tests were generated (LLM returned no test files).")
    else:
        for r in e2e_results:
            if r.returncode == 0:
                lines.append(f"- {r.tool}: PASSED")
            elif r.timed_out:
                timeout_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(f"- {r.tool}: TIMED OUT ({timeout_snippet})")
            else:
                stderr_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(
                    f"- {r.tool}: FAILED (exit {r.returncode})\n{stderr_snippet}"
                )

    lines.append("")  # blank line before Static Analysis

    # --- Static Analysis section ---
    lines.append("**Static Analysis:**")
    if not static_results:
        lines.append(
            "- No static analysis tools detected.\n"
            "  (No pyproject.toml, setup.cfg, or package.json found in repository.)"
        )
    else:
        for r in static_results:
            if r.returncode == 0:
                lines.append(f"- {r.tool}: PASSED")
            elif r.timed_out:
                timeout_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(f"- {r.tool}: TIMED OUT ({timeout_snippet})")
            else:
                stderr_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(
                    f"- {r.tool}: FAILED (exit {r.returncode})\n{stderr_snippet}"
                )

    return "\n".join(lines)
