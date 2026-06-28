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

Phase 28 scope: live app container E2E (PWGEN-01..03, EXEC-01..02).
  T-28-01: ValueError from _detect_serve_command (no preview/start/dev script) →
           caught in Step 4d except clause; E2E skipped with skip note;
           unit tests and static analysis continue.
  T-28-02: ContainerStartError from managed_app_container (build failure or
           health-check timeout) → same except clause; skip note set; pipeline
           continues to Step 5.
"""

import glob
import logging
import os
import pathlib
import shlex
import shutil
import subprocess

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
from services.code_generator import FileChange
from services.pr_creator import apply_commit_push_and_open_pr
from services.test_executor import TestResult, ToolchainCommand, run_command, run_npm_audit_fix, run_static_analysis
from services.app_container import ContainerStartError, managed_app_container
from services.sonar_client import ensure_sonarqube_ready
from services.sonar_scanner import fetch_sonar_metrics, run_sonar_scan
from services.claude_code_executor import run_claude_playwright_generator
from services.test_generator import generate_e2e_tests, generate_unit_tests
from services.ticket_tracking import safe_record_transaction, safe_upsert_ticket_status

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


def _resolve_compose_network() -> str:
    """Return the Docker network name to use for playwright containers.

    Prefers COMPOSE_NETWORK env var when set. Otherwise inspects the backend
    container's own networks to find the one ending with '_ai-sdlc-net' — this
    guarantees we join the same network that the frontend service is on.
    Falls back to a docker network ls scan, then the bare name.
    """
    if override := os.environ.get("COMPOSE_NETWORK"):
        return override
    # Ask Docker which networks this container is connected to
    try:
        hostname = subprocess.run(
            ["hostname"], capture_output=True, text=True, timeout=3
        ).stdout.strip()
        out = subprocess.run(
            ["docker", "inspect", hostname, "--format", "{{json .NetworkSettings.Networks}}"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            import json as _json
            nets = _json.loads(out.stdout)
            for name in nets:
                if name.endswith("_ai-sdlc-net"):
                    return name
    except Exception:  # noqa: BLE001
        pass
    # Fallback: pick the shortest matching network name (most likely the direct compose project)
    try:
        out = subprocess.run(
            ["docker", "network", "ls", "--format", "{{.Name}}", "--filter", "name=ai-sdlc-net"],
            capture_output=True, text=True, timeout=5,
        )
        candidates = [n.strip() for n in out.stdout.splitlines() if n.strip().endswith("_ai-sdlc-net")]
        if candidates:
            return min(candidates, key=len)  # shortest = least-nested compose project
    except Exception:  # noqa: BLE001
        pass
    return "ai-sdlc-net"


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


def _run_sonar_step(cloned, compose_network: str, issue_key: str) -> "TestResult | None":
    """Execute sonar-scanner + CE task poll. SCAN-01..04.

    Returns None if SONAR_URL not set. Never raises.
    """
    sonar_url = os.environ.get("SONAR_URL")
    if not sonar_url:
        logger.info("SONAR_URL not set — skipping sonar scan for %s", issue_key)
        return None
    project_key = f"{cloned.owner}__{cloned.repo}"
    timeout_secs = int(os.environ.get("SONAR_TIMEOUT_SECONDS", "300"))
    try:
        ensure_sonarqube_ready()  # bootstraps SONAR_TOKEN; raises SonarQubeNotReadyError if down
        sonar_token = os.environ.get("SONAR_TOKEN")
        if not sonar_token:
            return TestResult(
                tool="sonar-scanner",
                returncode=1,
                stdout="",
                stderr="SONAR_TOKEN not available after SonarQube bootstrap",
                timed_out=False,
            )
        return run_sonar_scan(
            workspace_path=cloned.workspace_path,
            project_key=project_key,
            sonar_url=sonar_url,
            token=sonar_token,
            compose_network=compose_network,
            timeout_secs=timeout_secs,
        )
    except Exception as exc:
        logger.warning("Sonar scan error for %s: %s", issue_key, exc)
        return TestResult(
            tool="sonar-scanner",
            returncode=2,
            stdout="",
            stderr=f"Sonar scan error: {exc}",
            timed_out=False,
        )


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

    # Ticket-tracking bookkeeping (best-effort).
    safe_upsert_ticket_status(
        db, project.id, issue_key, pipeline_stage="qa",
        current_status="QA pipeline started",
    )
    safe_record_transaction(
        db, project.id, issue_key, "qa", "QA pipeline started", status="in_progress"
    )

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
    e2e_results: list[TestResult] = []
    static_results: list[TestResult] = []
    playwright_py_results: list[TestResult] = []
    sonar_result: TestResult | None = None
    sonar_metrics = None
    autofix_pr_url: str | None = None
    npm_audit_fix_pr_url: str | None = None
    e2e_live_url: str | None = None
    still_failing = False
    compose_network = _resolve_compose_network()

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
            # T-24-01: Reject any path escaping the workspace root (traversal guard only)
            resolved = (workspace_root / change.path).resolve()
            if not str(resolved).startswith(str(workspace_root) + "/"):
                logger.warning(
                    "Skipping generated test file due to path-traversal violation: %s", change.path
                )
                continue

            # File I/O and execution outside the narrow traversal catch
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
                        f"npm ci --silent && npm test -- {shlex.quote(change.path)}",
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
            if result.returncode != 0:
                logger.info("Test stdout:\n%s", result.stdout[:3000] if result.stdout else "(empty)")
                logger.info("Test stderr:\n%s", result.stderr[:3000] if result.stderr else "(empty)")

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

        # Step 4e — Generate Python Playwright tests now (no live app needed for generation).
        # Execution is deferred into the managed_app_container block below.
        pw_py_file_changes = await run_claude_playwright_generator(
            workspace_path=cloned.workspace_path,
            issue_key=issue_key,
            issue_summary=issue_summary,
            issue_description=issue_description,
            codebase_context=codebase_context,
            relevant_file_contents=relevant_file_contents,
        )
        # Write generated test files to workspace so they are available for execution.
        pw_py_paths: list[str] = []
        for change in pw_py_file_changes:
            resolved = (workspace_root / change.path).resolve()
            if not str(resolved).startswith(str(workspace_root) + "/"):
                logger.warning("Skipping Playwright file (path-traversal): %s", change.path)
                continue
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(change.content, encoding="utf-8")
            logger.info("Wrote Python Playwright test file: %s", change.path)
            pw_py_paths.append(change.path)

        # Step 4d/4e — Spin up live app, run E2E and Python Playwright tests against it.
        # T-28-01: ValueError = no serve script → graceful skip.
        # T-28-02: ContainerStartError = build/timeout failure → graceful skip.
        e2e_skip_note: str | None = None
        try:
            with managed_app_container(cloned.workspace_path, compose_network) as playwright_deployment_url:
                e2e_live_url = playwright_deployment_url
                playwright_configs = glob.glob(
                    os.path.join(cloned.workspace_path, "playwright.config.*")
                )
                if not playwright_configs:
                    logger.info("No playwright.config.* found in workspace — skipping E2E generation")
                    e2e_skip_note = "E2E tests skipped (no playwright.config.* detected in repository)."
                else:
                    e2e_file_changes = generate_e2e_tests(
                        issue_key=issue_key,
                        issue_summary=issue_summary,
                        issue_description=issue_description,
                        codebase_context=codebase_context,
                        relevant_file_contents=relevant_file_contents,
                    )
                    for change in e2e_file_changes:
                        # T-24-01: traversal guard only
                        resolved = (workspace_root / change.path).resolve()
                        if not str(resolved).startswith(str(workspace_root) + "/"):
                            logger.warning(
                                "Skipping generated E2E file due to path-traversal violation: %s",
                                change.path,
                            )
                            continue

                        resolved.parent.mkdir(parents=True, exist_ok=True)
                        resolved.write_text(change.content, encoding="utf-8")
                        logger.info("Wrote generated E2E test file: %s", change.path)

                        image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
                        cmd = ToolchainCommand(
                            name="playwright",
                            command=[
                                "docker", "run", "--rm",
                                "--network", compose_network,
                                "-v", f"{cloned.workspace_path}:/workspace",
                                "-w", "/workspace",
                                "-e", f"BASE_URL={playwright_deployment_url}",
                                image,
                                "npx", "--yes", "@playwright/test", "test", f"/workspace/{change.path}",
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
                        if result.stdout:
                            logger.info("E2E stdout:\n%s", result.stdout[:3000])
                        if result.stderr:
                            logger.info("E2E stderr:\n%s", result.stderr[:2000])

                # Execute pre-generated Python Playwright tests against the live app.
                image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
                for path in pw_py_paths:
                    cmd = ToolchainCommand(
                        name=f"playwright-py:{path}",
                        command=[
                            "docker", "run", "--rm",
                            "--network", compose_network,
                            "-v", f"{cloned.workspace_path}:/workspace",
                            "-e", f"BASE_URL={playwright_deployment_url}",
                            image,
                            "python", "-m", "pytest", f"/workspace/{path}",
                            "--browser", "chromium", "--tb=short", "-q",
                        ],
                    )
                    result = run_command(cmd)
                    playwright_py_results.append(result)
                    logger.info(
                        "Python Playwright test %s exit=%d timed_out=%s",
                        path, result.returncode, result.timed_out,
                    )
                    if result.returncode != 0:
                        logger.info("Playwright stdout:\n%s", result.stdout[:3000] if result.stdout else "(empty)")
                        logger.info("Playwright stderr:\n%s", result.stderr[:3000] if result.stderr else "(empty)")

        except (ValueError, ContainerStartError, OSError) as exc:
            # T-28-01 / T-28-02: No serve script or container failed to start.
            # OSError covers FileNotFoundError from _detect_serve_command when
            # package.json is absent (Python-only projects).
            # E2E is skipped; unit tests and static analysis continue (Step 5 below).
            e2e_skip_note = f"E2E tests skipped: {exc}"
            logger.warning("E2E stage skipped for %s: %s", issue_key, exc)

        # Step 5 — Run static analysis tools via Docker subprocess.
        # JS tools run npm ci first, so 300s timeout (vs default 120s).
        static_results = run_static_analysis(cloned.workspace_path, timeout=300)

        # Step 5.2 — SonarQube scan (SCAN-01..04).
        sonar_result = _run_sonar_step(cloned, compose_network, issue_key)

        # Step 5.3 — Fetch SonarQube quality metrics if scan succeeded (REPORT-02).
        # Read env vars again — cheap, avoids refactoring _run_sonar_step return type.
        if sonar_result is not None and sonar_result.returncode == 0:
            _sonar_url = os.environ.get("SONAR_URL", "")
            _sonar_token = os.environ.get("SONAR_TOKEN", "")
            if _sonar_url and _sonar_token:
                _project_key = f"{cloned.owner}__{cloned.repo}"
                sonar_metrics = fetch_sonar_metrics(_project_key, _sonar_url, _sonar_token)

        # Step 5.1 — npm audit auto-fix: if npm_audit failed, run `npm audit fix`
        # in Docker and open a PR with the updated lockfile.
        npm_audit_failed = any(
            r.tool == "npm_audit" and r.returncode != 0 and not r.timed_out
            for r in static_results
        )
        if npm_audit_failed:
            changed_paths = run_npm_audit_fix(cloned.workspace_path)
            if changed_paths:
                file_changes = [
                    FileChange(
                        path=p,
                        content=pathlib.Path(cloned.workspace_path, p).read_text(errors="replace"),
                    )
                    for p in changed_paths
                ]
                try:
                    npm_pr = apply_commit_push_and_open_pr(
                        cloned.workspace_path,
                        github_repo,
                        github_token,
                        issue_key,
                        file_changes,
                        pr_title=f"fix: npm audit fix for {issue_key}",
                        pr_body=(
                            f"Auto-fix for npm audit vulnerabilities detected during QA "
                            f"for {issue_key}. Review and merge to resolve security findings."
                        ),
                        branch_name=f"jarvis/npm-audit-fix-{issue_key}",
                    )
                    npm_audit_fix_pr_url = npm_pr.html_url
                    logger.info("npm audit fix PR opened for %s: %s", issue_key, npm_audit_fix_pr_url)
                except Exception:
                    logger.exception("npm audit fix PR creation failed for %s", issue_key)

        comment_text = _format_qa_comment(
            unit_test_results, e2e_results, static_results, issue_key,
            e2e_skip_note, playwright_py_results, e2e_live_url=e2e_live_url,
            sonar_result=sonar_result,
        )
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

        if npm_audit_fix_pr_url:
            comment_text += f"\n\nnpm audit fix PR: {npm_audit_fix_pr_url}"
        elif npm_audit_failed:
            comment_text += "\n\nnpm audit fix: could not auto-fix — review manually."

        # Mark pipeline complete on success.
        state_row.status = "complete"
        state_row.draft_content = comment_text
        db.commit()

        safe_upsert_ticket_status(
            db, project.id, issue_key, pipeline_stage="qa",
            current_status="QA pipeline completed",
        )
        safe_record_transaction(
            db, project.id, issue_key, "qa", "QA pipeline completed",
            status="success", result_url=autofix_pr_url or None,
        )

    except Exception as exc:
        state_row.status = "failed"
        try:
            db.commit()
        except Exception:
            db.rollback()
        safe_upsert_ticket_status(
            db, project.id, issue_key, pipeline_stage="qa",
            current_status="QA pipeline failed",
        )
        safe_record_transaction(
            db, project.id, issue_key, "qa", "QA pipeline failed",
            status="failed", detail=str(exc),
        )
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
        remediation_html = _build_remediation_html(
            unit_test_results, e2e_results, static_results, autofix_pr_url, still_failing,
            npm_audit_fix_pr_url=npm_audit_fix_pr_url,
            playwright_py_results=playwright_py_results,
            sonar_metrics=sonar_metrics,
        )
        qa_page_url = await publish_qa_report(
            project, issue_key, comment_text, remediation_html, sonar_metrics=sonar_metrics
        )
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
    playwright_py_results: list[TestResult] | None = None,
    e2e_live_url: str | None = None,
    sonar_result: "TestResult | None" = None,
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
    e2e_header = f"**E2E Tests (live: {e2e_live_url}):**" if e2e_live_url else "**E2E Tests:**"
    lines.append(e2e_header)
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

    # --- Python Playwright Evaluation section ---
    lines.append("")
    lines.append("**Python Playwright Evaluation:**")
    if not playwright_py_results:
        lines.append("- Skipped (CLAUDE_API_KEY not set or no tests generated).")
    else:
        for r in playwright_py_results:
            if r.returncode == 0:
                lines.append(f"- {r.tool}: PASSED")
            elif r.timed_out:
                timeout_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(f"- {r.tool}: TIMED OUT ({timeout_snippet})")
            else:
                stderr_snippet = r.stderr[:500] if r.stderr else ""
                lines.append(f"- {r.tool}: FAILED (exit {r.returncode})\n{stderr_snippet}")

    # --- SonarQube Scan section ---
    lines.append("")
    lines.append("**SonarQube Scan:**")
    if sonar_result is None:
        lines.append("- Skipped (SONAR_URL or SONAR_TOKEN not configured).")
    elif sonar_result.returncode == 0:
        lines.append(f"- sonar-scanner: SUCCESS — {sonar_result.stderr}")
    elif sonar_result.timed_out:
        lines.append(f"- sonar-scanner: TIMED OUT — {sonar_result.stderr}")
    else:
        lines.append(f"- sonar-scanner: FAILED (exit {sonar_result.returncode}) — {sonar_result.stderr[:200]}")

    return "\n".join(lines)


def _build_remediation_html(
    unit_test_results: list[TestResult],
    e2e_results: list[TestResult],
    static_results: list[TestResult],
    autofix_pr_url: str | None,
    still_failing: bool,
    npm_audit_fix_pr_url: str | None = None,
    playwright_py_results: list[TestResult] | None = None,
    sonar_metrics: "SonarMetrics | None" = None,
) -> str:
    """Build an HTML Remediation Steps section for the Confluence QA page.

    Returns an empty string when all checks passed (no section needed).
    """
    items: list[str] = []

    unit_failures = [r for r in unit_test_results if r.returncode != 0 and not r.timed_out]
    e2e_failures = [r for r in e2e_results if r.returncode != 0 and not r.timed_out]
    static_failures = [r for r in static_results if r.returncode != 0 and not r.timed_out]
    pw_py_failures = [r for r in (playwright_py_results or []) if r.returncode != 0 and not r.timed_out]
    sonar_failed = sonar_metrics is not None and sonar_metrics.gate_status == "FAILED"

    if not (unit_failures or e2e_failures or static_failures or pw_py_failures or sonar_failed):
        return ""

    if unit_failures:
        if autofix_pr_url and still_failing:
            items.append(
                f"<li><strong>Unit Tests:</strong> Auto-fix exhausted all attempts. "
                f"Review the partial fixes in the <a href=\"{autofix_pr_url}\">auto-fix PR</a> "
                f"and complete the fix manually.</li>"
            )
        elif autofix_pr_url:
            items.append(
                f"<li><strong>Unit Tests:</strong> Auto-fix applied — "
                f"review and merge the <a href=\"{autofix_pr_url}\">auto-fix PR</a>.</li>"
            )
        else:
            items.append(
                "<li><strong>Unit Tests:</strong> Run <code>pytest</code> locally to "
                "reproduce failures, then fix the implementation or update the tests.</li>"
            )

    if e2e_failures:
        items.append(
            "<li><strong>E2E Tests:</strong> Re-run against a live instance to confirm "
            "failures, then fix selectors or expectations in the generated test file.</li>"
        )

    for r in static_failures:
        if r.tool == "npm_audit":
            if npm_audit_fix_pr_url:
                items.append(
                    f"<li><strong>npm audit:</strong> Auto-fix PR raised — "
                    f"review and merge <a href=\"{npm_audit_fix_pr_url}\">the fix PR</a> "
                    f"to resolve vulnerabilities.</li>"
                )
            else:
                items.append(
                    "<li><strong>npm audit:</strong> Run <code>npm audit fix</code> locally "
                    "to resolve vulnerabilities, then commit the updated lockfile.</li>"
                )
        else:
            items.append(
                f"<li><strong>{r.tool}:</strong> Run <code>{r.tool}</code> locally to see "
                f"violations and fix them before re-running QA.</li>"
            )

    if pw_py_failures:
        items.append(
            "<li><strong>Python Playwright Evaluation:</strong> Run "
            "<code>pytest tests/playwright/ --browser chromium</code> locally to reproduce "
            "failures and fix the implementation or test selectors.</li>"
        )

    if sonar_failed and sonar_metrics:
        issue_rows = ""
        if sonar_metrics.issues:
            rows = []
            for iss in sonar_metrics.issues:
                loc = f"{iss.file}:{iss.line}" if iss.line else iss.file
                rows.append(
                    f"<tr><td><code>{loc}</code></td>"
                    f"<td>{iss.severity}</td>"
                    f"<td>{iss.type.replace('_', ' ')}</td>"
                    f"<td>{iss.message}</td></tr>"
                )
            issue_rows = (
                "<table><tr><th>Location</th><th>Severity</th>"
                "<th>Type</th><th>Issue</th></tr>"
                + "".join(rows)
                + "</table>"
            )
        else:
            issue_rows = "<p>No specific issues retrieved — re-scan to get details.</p>"
        items.append(
            f"<li><strong>SonarQube Quality Gate FAILED</strong> — fix the following "
            f"before re-triggering QA:{issue_rows}</li>"
        )

    return "<ul>" + "".join(items) + "</ul>"
