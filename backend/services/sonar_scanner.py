"""sonar-scanner CLI invocation and CE task polling — SCAN-01, SCAN-02, SCAN-03, SCAN-04."""

import logging
import os
import pathlib
import time

import httpx

from services.test_executor import TestResult, ToolchainCommand, run_command

logger = logging.getLogger(__name__)

_CE_POLL_INTERVAL = 5  # seconds between CE task polls


def _read_ce_task_id(workspace_path: str) -> str | None:
    """Read ceTaskId from .scannerwork/report-task.txt. Returns None if absent."""
    report = pathlib.Path(workspace_path) / ".scannerwork" / "report-task.txt"
    if not report.exists():
        return None
    for line in report.read_text(encoding="utf-8").splitlines():
        if line.startswith("ceTaskId="):
            return line.split("=", 1)[1]
    return None


def _poll_ce_task(sonar_url: str, task_id: str, token: str, timeout_secs: int) -> str:
    """Poll /api/ce/task until terminal status or timeout. Returns status string."""
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        try:
            r = httpx.get(
                f"{sonar_url}/api/ce/task",
                params={"id": task_id},
                headers={"Authorization": f"Bearer {token}"},
                timeout=10.0,
            )
            if r.status_code == 200:
                status = r.json().get("task", {}).get("status", "")
                if status in ("SUCCESS", "FAILED", "CANCELLED"):
                    return status
        except httpx.RequestError:
            pass  # SonarQube momentarily unreachable — keep polling
        time.sleep(_CE_POLL_INTERVAL)
    return "TIMEOUT"


def run_sonar_scan(
    workspace_path: str,
    project_key: str,
    sonar_url: str,
    token: str,
    compose_network: str,
    timeout_secs: int = 300,
) -> TestResult:
    """Run sonar-scanner-cli and poll CE task to completion. Never raises.

    All failure paths return TestResult with non-zero returncode.
    """
    project_name = project_key.replace("__", "/", 1)

    cmd = ToolchainCommand(
        name="sonar-scanner",
        command=[
            "docker", "run", "--rm",
            "--network", compose_network,
            "-v", f"{workspace_path}:/usr/src",
            "-e", f"SONAR_HOST_URL={sonar_url}",
            "-e", f"SONAR_TOKEN={token}",
            "sonarsource/sonar-scanner-cli:5",
            f"-Dsonar.projectKey={project_key}",
            f"-Dsonar.projectName={project_name}",
            "-Dsonar.sources=/usr/src",
            "-Dsonar.scm.disabled=true",
        ],
    )

    result = run_command(cmd, timeout=timeout_secs)

    if result.returncode != 0:
        return result

    task_id = _read_ce_task_id(workspace_path)
    if task_id is None:
        return TestResult(
            tool="sonar-scanner",
            returncode=1,
            stdout=result.stdout,
            stderr="Scanner exited 0 but .scannerwork/report-task.txt not found",
            timed_out=False,
        )

    ce_status = _poll_ce_task(sonar_url, task_id, token, timeout_secs)

    if ce_status == "SUCCESS":
        return TestResult(
            tool="sonar-scanner",
            returncode=0,
            stdout=result.stdout,
            stderr=f"CE task {task_id}: SUCCESS",
            timed_out=False,
        )
    if ce_status == "TIMEOUT":
        return TestResult(
            tool="sonar-scanner",
            returncode=1,
            stdout=result.stdout,
            stderr=f"CE task {task_id} polling timed out after {timeout_secs}s",
            timed_out=True,
        )
    # FAILED or CANCELLED
    return TestResult(
        tool="sonar-scanner",
        returncode=1,
        stdout=result.stdout,
        stderr=f"CE task {task_id}: {ce_status}",
        timed_out=False,
    )
