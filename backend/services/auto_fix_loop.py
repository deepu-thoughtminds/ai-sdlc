"""Bounded auto-fix loop — AUTOFIX-01, AUTOFIX-02, AUTOFIX-03.

On unit test failure, generates a targeted fix via freellmapi using the
specific failing test output (not full regeneration), applies it, and
re-runs only the failing tests — up to MAX_ATTEMPTS times. Terminates
early on non-progress (identical failure fingerprints across attempts).
Fix commits land on a `jarvis/qa-fix-{issue_key}` branch via a PR — never
pushed directly to main.

Threat mitigations:
  T-25-01: FileChange.path is resolved against workspace_root and rejected
           if it escapes the workspace (mirrors T-24-01 / T-15-06).
  T-25-02: FileChange.path under the `tests/` prefix is rejected — the
           auto-fix loop fixes source code, never the tests themselves.
  T-25-03: Fix prompt truncates stdout/stderr to 2000 chars each before
           interpolation (mirrors T-24-05 per-tool truncation).
  T-25-04: All fix commits go to `jarvis/qa-fix-{issue_key}` via
           apply_commit_push_and_open_pr — main is never targeted.
  T-25-05: Non-progress fingerprints are computed from raw (untruncated)
           stderr+stdout, compared as a frozenset (order-independent).
"""

import hashlib
import logging
import os
import pathlib

from repositories import pipeline_state_repo
from services.code_generator import FileChange, _parse_file_changes
from services.llm_router import route_request
from services.pr_creator import apply_commit_push_and_open_pr
from services.reasoning import REASONING_INSTRUCTION, split_reasoning
from services.test_executor import TestResult, ToolchainCommand, run_command
from services.ticket_tracking import safe_record_agent_event, safe_record_reasoning

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
_TRUNCATE_LEN = 2000


def _fingerprint(results: list[TestResult]) -> frozenset:
    """Hash each failing result's raw stdout+stderr for non-progress detection (T-25-05)."""
    return frozenset(
        hashlib.sha256((r.stdout + r.stderr).encode("utf-8", errors="replace")).hexdigest()
        for r in results
        if r.returncode != 0 and not r.timed_out
    )


def _rerun_failing_tests(workspace_path: str, failing: list[TestResult]) -> list[TestResult]:
    """Re-run each failing test file using the same runner it was originally run with.

    Mirrors the extension-based dispatch in qa_pipeline.py (TESTGEN-04) so
    .test.ts(x)/.spec.ts(x) files go to npm test, .py files go to pytest.
    node_modules from a prior npm ci in the same workspace mount are reused.
    """
    image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
    results: list[TestResult] = []
    for r in failing:
        fp = r.file_path
        if fp.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
            cmd = ToolchainCommand(
                name="npm test",
                command=[
                    "docker", "run", "--rm",
                    "-v", f"{workspace_path}:/workspace",
                    "-w", "/workspace",
                    image,
                    "sh", "-c",
                    f"test -d node_modules || npm ci --silent && npm test -- {fp}",
                ],
            )
            new_result = run_command(cmd, timeout=300)
        else:
            cmd = ToolchainCommand(
                name="pytest",
                command=[
                    "docker", "run", "--rm",
                    "-v", f"{workspace_path}:/workspace",
                    image,
                    "pytest", f"/workspace/{fp}", "-v",
                ],
            )
            new_result = run_command(cmd)
        new_result.file_path = fp
        results.append(new_result)
    return results


def _build_fix_prompt(failing: list[TestResult]) -> str:
    sections = []
    for r in failing:
        stdout = r.stdout[:_TRUNCATE_LEN]
        stderr = r.stderr[:_TRUNCATE_LEN]
        sections.append(f"Tool: {r.tool}\nstdout:\n{stdout}\nstderr:\n{stderr}")
    return (
        "The following test(s) are failing. Generate a targeted fix for the "
        "application source code (NOT the test files). For each file you change, "
        "use EXACTLY this format:\n\n"
        "### FILE: path/to/file\n"
        "```\n"
        "<complete file content here>\n"
        "```\n\n"
        + "\n\n".join(sections)
        + REASONING_INSTRUCTION
    )


def _apply_fix(workspace_path: str, change: FileChange) -> bool:
    """Write a single FileChange to disk with path-traversal and test-file guards.

    Returns True if applied, False if rejected (T-25-01, T-25-02).
    """
    if change.path.startswith("tests/"):
        logger.warning("Rejecting auto-fix change to test file: %s", change.path)
        return False
    workspace_root = pathlib.Path(workspace_path).resolve()
    try:
        resolved = (workspace_root / change.path).resolve()
        if not str(resolved).startswith(str(workspace_root) + "/"):
            raise ValueError(
                f"FileChange path escapes workspace: '{change.path}' resolves to '{resolved}'"
            )
    except ValueError as ve:
        logger.warning("Rejecting auto-fix change due to path-traversal: %s", ve)
        return False
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(change.content, encoding="utf-8")
    return True


def run_auto_fix_loop(
    unit_test_results: list[TestResult],
    workspace_path: str,
    issue_key: str,
    github_repo: str,
    github_token: str,
    state_row,
    db,
) -> tuple[list[TestResult], str | None]:
    """Attempt up to MAX_ATTEMPTS targeted fixes for failing unit tests.

    AUTOFIX-01: Each attempt sends only the specific failing output to
    freellmapi (not full test regeneration), applies the resulting fix,
    and re-runs only the failing tests.
    AUTOFIX-02: Terminates early if the same failure fingerprint repeats.
    AUTOFIX-03: Opens a PR on `jarvis/qa-fix-{issue_key}` for any applied
    fix — never pushes directly to main.

    Returns:
        (final test results, PR URL or None if no fix was opened)
    """
    failing = [r for r in unit_test_results if r.returncode != 0 and not r.timed_out]
    if not failing:
        return unit_test_results, None

    prev_fingerprint: frozenset | None = None
    pr_url: str | None = None
    any_fix_applied = False
    current_results = unit_test_results

    for attempt in range(1, MAX_ATTEMPTS + 1):
        fingerprint = _fingerprint(failing)
        if prev_fingerprint is not None and fingerprint == prev_fingerprint:
            logger.info("Auto-fix non-progress detected for %s — stopping early", issue_key)
            break
        prev_fingerprint = fingerprint

        prompt = _build_fix_prompt(failing)
        response = route_request(stage="autofix", prompt=prompt)
        reasoning, answer = split_reasoning(response.content)
        if response.reasoning:
            reasoning = response.reasoning
        safe_record_agent_event(
            db, state_row.project_id, issue_key, "qa", "decision",
            f"Auto-fix attempt {attempt}/{MAX_ATTEMPTS}",
        )
        safe_record_reasoning(db, state_row.project_id, issue_key, "qa", reasoning)
        changes = _parse_file_changes(answer)

        applied = [c for c in changes if _apply_fix(workspace_path, c)]

        pipeline_state_repo.update(db, state_row.id, qa_attempt=attempt)
        state_row.qa_attempt = attempt  # keep local copy in sync

        if applied:
            any_fix_applied = True
            try:
                pr = apply_commit_push_and_open_pr(
                    workspace_path,
                    github_repo,
                    github_token,
                    issue_key,
                    applied,
                    pr_title=f"fix(qa): auto-fix {issue_key} — attempt {attempt}/{MAX_ATTEMPTS}",
                    branch_name=f"jarvis/qa-fix-{issue_key}",
                )
                pr_url = pr.html_url
            except Exception:
                logger.exception("Auto-fix PR creation failed for %s", issue_key)

        rerun = _rerun_failing_tests(workspace_path, failing)
        current_results = rerun
        failing = [r for r in rerun if r.returncode != 0 and not r.timed_out]

        if not failing:
            break

    return current_results, pr_url if any_fix_applied else None
