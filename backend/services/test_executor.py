"""QA test executor — TESTEXEC-01, TESTEXEC-02, TESTGEN-02.

Pure-function module (no ORM, no async) that auto-detects the project's
toolchain by reading the workspace filesystem, then shells out to Docker to
run the relevant static-analysis tools.

Architectural boundary: this module ONLY runs tools. LLM test generation
is handled by qa_pipeline.py / Phase 24. detect_toolchain() performs NO
LLM calls.

Threat mitigations:
  T-23-01: All subprocess.run() calls use list-form args — shell=True is
           NEVER used. This prevents shell-injection via workspace paths.
  T-23-02: subprocess.TimeoutExpired is caught per-command; timed_out=True
           is set on the returned TestResult and the loop continues — the
           pipeline is never left hanging on a stalled Docker container.
"""

import logging
import os
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ToolchainCommand:
    """A single static-analysis tool command ready to pass to subprocess.run().

    Fields:
        name:    Human-readable tool name (e.g. "ruff", "eslint").
        command: Full Docker run command list — passed directly to
                 subprocess.run(); never constructed with shell=True.
    """

    name: str
    command: list = field(default_factory=list)


@dataclass
class TestResult:
    """Result of running a single toolchain command.

    Fields:
        tool:       Same as ToolchainCommand.name used to produce this result.
        returncode: Process exit code; -1 when the command timed out.
        stdout:     Captured standard output (text).
        stderr:     Captured standard error (text).
        timed_out:  True when subprocess.TimeoutExpired was caught (T-23-02).
        file_path:  Relative path of the test file that produced this result
                    (populated by qa_pipeline for unit test results; empty for
                    static analysis results). Used by auto_fix_loop to re-run
                    the same file with the same runner.
    """

    tool: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool
    file_path: str = ""


def detect_toolchain(workspace_path: str) -> list[ToolchainCommand]:
    """Auto-detect the project toolchain by reading the workspace filesystem.

    TESTEXEC-01: No LLM call is made. Detection is purely file-system based.

    Logic:
      1. If pyproject.toml OR setup.cfg exists → Python project.
         Adds: ruff, mypy, bandit (all via Docker).
      2. If package.json exists → JS/TS project.
         Adds: eslint, npm_audit.
         If tsconfig.json also exists → Adds tsc.

    Args:
        workspace_path: Absolute path to the cloned repository workspace.

    Returns:
        Ordered list of ToolchainCommand objects to run. Empty list if no
        recognised indicator files are found.
    """
    image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
    commands: list[ToolchainCommand] = []

    # Python detection
    has_pyproject = os.path.isfile(os.path.join(workspace_path, "pyproject.toml"))
    has_setup_cfg = os.path.isfile(os.path.join(workspace_path, "setup.cfg"))

    if has_pyproject or has_setup_cfg:
        commands.extend([
            ToolchainCommand(
                name="ruff",
                command=[
                    "docker", "run", "--rm",
                    "-v", f"{workspace_path}:/workspace",
                    image,
                    "ruff", "check", "/workspace",
                ],
            ),
            ToolchainCommand(
                name="mypy",
                command=[
                    "docker", "run", "--rm",
                    "-v", f"{workspace_path}:/workspace",
                    image,
                    "mypy", "/workspace", "--ignore-missing-imports",
                ],
            ),
            ToolchainCommand(
                name="bandit",
                command=[
                    "docker", "run", "--rm",
                    "-v", f"{workspace_path}:/workspace",
                    image,
                    "bandit", "-r", "/workspace", "-q",
                ],
            ),
        ])

    # JS/TS detection
    has_package_json = os.path.isfile(os.path.join(workspace_path, "package.json"))

    if has_package_json:
        # Detect package manager from lockfile — determines install command and
        # audit command. Without a lockfile we can't do a reproducible install,
        # so JS analysis tools are skipped.
        has_package_lock = os.path.isfile(os.path.join(workspace_path, "package-lock.json"))
        has_yarn_lock = os.path.isfile(os.path.join(workspace_path, "yarn.lock"))
        has_pnpm_lock = os.path.isfile(os.path.join(workspace_path, "pnpm-lock.yaml"))

        if has_package_lock:
            install_cmd = "npm ci --silent"
            audit_cmd = "npm audit --audit-level=high"
        elif has_yarn_lock:
            install_cmd = "yarn install --frozen-lockfile --silent"
            audit_cmd = "yarn audit --level high"
        elif has_pnpm_lock:
            install_cmd = "pnpm install --frozen-lockfile --silent"
            audit_cmd = "pnpm audit --audit-level high"
        else:
            install_cmd = None
            audit_cmd = None
            logger.warning(
                "No lockfile found for JS project at %s — skipping JS static analysis",
                workspace_path,
            )

        if install_cmd:
            # All JS tools: install deps first so eslint-config-next and other
            # extended configs resolve from the repo's own node_modules. Each
            # tool checks for node_modules before re-installing — the unit test
            # step may have already populated it in the same mounted workspace,
            # so static analysis can reuse those modules (sequential execution,
            # no race condition).
            reuse_install = f"test -d node_modules || {install_cmd}"
            commands.append(
                ToolchainCommand(
                    name="eslint",
                    command=[
                        "docker", "run", "--rm",
                        "-v", f"{workspace_path}:/workspace",
                        "-w", "/workspace",
                        image,
                        "sh", "-c",
                        f"{reuse_install} && npx eslint . --ext .js,.ts,.jsx,.tsx",
                    ],
                )
            )
            commands.append(
                ToolchainCommand(
                    name="npm_audit",
                    command=[
                        "docker", "run", "--rm",
                        "-v", f"{workspace_path}:/workspace",
                        "-w", "/workspace",
                        image,
                        "sh", "-c",
                        f"{reuse_install} && {audit_cmd}",
                    ],
                )
            )

            # TypeScript detection (tsc only if tsconfig.json present)
            has_tsconfig = os.path.isfile(os.path.join(workspace_path, "tsconfig.json"))
            if has_tsconfig:
                commands.append(
                    ToolchainCommand(
                        name="tsc",
                        command=[
                            "docker", "run", "--rm",
                            "-v", f"{workspace_path}:/workspace",
                            "-w", "/workspace",
                            image,
                            "sh", "-c",
                            f"{reuse_install} && npx tsc --noEmit",
                        ],
                    )
                )

    return commands


def run_command(cmd: ToolchainCommand, timeout: int = 120) -> TestResult:
    """Execute a single toolchain command via subprocess.run().

    TESTEXEC-02: Runs the Docker command as a subprocess with a hard timeout.
    T-23-01: Uses list-form args — shell=True is NEVER used.
    T-23-02: Catches subprocess.TimeoutExpired; sets timed_out=True and
             returns without re-raising so the pipeline continues.

    Args:
        cmd:     ToolchainCommand whose .command list is passed to subprocess.run().
        timeout: Per-command hard timeout in seconds (default 120).

    Returns:
        TestResult with stdout, stderr, returncode, and timed_out populated.

    Raises:
        Exception: Any exception other than TimeoutExpired propagates to the
                   caller (qa_pipeline.py handles it in its try/except block).
    """
    logger.info("Executing tool %s: %s", cmd.name, cmd.command)
    try:
        proc = subprocess.run(
            cmd.command,
            capture_output=True,
            text=True,
            timeout=timeout,
            # T-23-01: shell=True is NEVER used — list-form args only.
        )
        return TestResult(
            tool=cmd.name,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        # T-23-02: Timeout caught — pipeline continues with next tool.
        logger.warning("Tool %s timed out after %ds", cmd.name, timeout)
        return TestResult(
            tool=cmd.name,
            returncode=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            timed_out=True,
        )


def run_static_analysis(workspace_path: str, timeout: int = 120) -> list[TestResult]:
    """Run all detected toolchain commands against the workspace.

    TESTEXEC-01: Detects tools without any LLM call.
    TESTEXEC-02: Runs each tool via Docker subprocess with timeout.

    Args:
        workspace_path: Absolute path to the cloned repository workspace.
        timeout:        Per-command timeout forwarded to run_command().

    Returns:
        List of TestResult objects, one per detected tool (in order).
        Empty list if no toolchain was detected.
    """
    commands = detect_toolchain(workspace_path)
    results: list[TestResult] = []
    for cmd in commands:
        logger.info("Running static analysis: %s", cmd.name)
        result = run_command(cmd, timeout=timeout)
        results.append(result)
        logger.info(
            "%s exit=%d timed_out=%s",
            cmd.name,
            result.returncode,
            result.timed_out,
        )
    return results


def run_npm_audit_fix(workspace_path: str, timeout: int = 300) -> list[str]:
    """Run `npm audit fix` in Docker; return relative paths of files that changed.

    Called after an `npm_audit` tool failure to attempt automatic remediation.
    Runs the fix command against the bind-mounted workspace so npm mutates
    package-lock.json (and package.json for non-breaking semver bumps) in place.

    T-23-01: list-form args — shell=True is never used.

    Returns:
        Relative file paths (e.g. ["package-lock.json"]) that were modified by
        the fix. Empty list if nothing changed, no package.json exists, or no
        lockfile is present (same skip conditions as detect_toolchain).
    """
    has_package_json = os.path.isfile(os.path.join(workspace_path, "package.json"))
    if not has_package_json:
        return []

    has_package_lock = os.path.isfile(os.path.join(workspace_path, "package-lock.json"))
    has_yarn_lock = os.path.isfile(os.path.join(workspace_path, "yarn.lock"))
    has_pnpm_lock = os.path.isfile(os.path.join(workspace_path, "pnpm-lock.yaml"))

    if has_package_lock:
        fix_cmd = "npm ci --silent && npm audit fix"
    elif has_yarn_lock:
        fix_cmd = "yarn install --frozen-lockfile --silent && yarn audit --fix"
    elif has_pnpm_lock:
        fix_cmd = "pnpm install --frozen-lockfile --silent && pnpm audit --fix"
    else:
        return []

    image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
    cmd = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{workspace_path}:/workspace",
            "-w", "/workspace",
            image,
            "sh", "-c", fix_cmd,
        ],
        capture_output=True,
        timeout=timeout,
    )
    logger.info("npm audit fix exit=%d", cmd.returncode)

    # Detect which files changed by asking git — workspace is a git clone.
    diff = subprocess.run(
        ["git", "-C", workspace_path, "diff", "--name-only"],
        capture_output=True,
        text=True,
    )
    changed = [p.strip() for p in diff.stdout.splitlines() if p.strip()]
    logger.info("npm audit fix changed files: %s", changed)
    return changed
