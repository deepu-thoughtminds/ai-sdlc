"""sonar-scanner CLI invocation and CE task polling — SCAN-01, SCAN-02, SCAN-03, SCAN-04."""

import logging
import os
import pathlib
import time
from dataclasses import dataclass

import httpx

from services.test_executor import TestResult, ToolchainCommand, run_command

logger = logging.getLogger(__name__)


@dataclass
class SonarIssue:
    file: str       # component path after the project key prefix
    line: int | None
    message: str
    severity: str   # BLOCKER, CRITICAL, MAJOR, MINOR, INFO
    type: str       # BUG, VULNERABILITY, CODE_SMELL, SECURITY_HOTSPOT


@dataclass
class SonarMetrics:
    gate_status: str        # "PASSED" or "FAILED"
    bugs: int
    vulnerabilities: int
    code_smells: int
    coverage: float | None  # None when not measured (no tests)
    duplications: float
    dashboard_url: str
    security_hotspots: int = 0
    ncloc: int = 0          # lines of code (excluding blanks/comments)
    issues: list[SonarIssue] = None  # top issues fetched when gate FAILED

    def __post_init__(self):
        if self.issues is None:
            self.issues = []


def fetch_sonar_metrics(
    project_key: str, sonar_url: str, token: str
) -> "SonarMetrics | None":
    """Fetch quality metrics from SonarQube measures API. Returns None on any failure.

    Single GET to /api/measures/component with all required metricKeys.
    Never raises — all exceptions are caught and logged as warnings.
    Dashboard URL: {sonar_url}/dashboard?id={project_key}
    """
    metric_keys = "alert_status,bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density,security_hotspots,ncloc"
    try:
        r = httpx.get(
            f"{sonar_url}/api/measures/component",
            params={"component": project_key, "metricKeys": metric_keys},
            auth=(token, ""),  # SonarQube <10: token as basic-auth username
            timeout=10.0,
        )
        r.raise_for_status()
        measures_list = r.json()["component"]["measures"]
        # Build a lookup dict: metric name → value string
        by_metric = {m["metric"]: m.get("value", "") for m in measures_list}

        raw_status = by_metric.get("alert_status", "ERROR")
        gate_status = "PASSED" if raw_status == "OK" else "FAILED"

        coverage_raw = by_metric.get("coverage")
        coverage = float(coverage_raw) if coverage_raw not in (None, "") else None

        metrics = SonarMetrics(
            gate_status=gate_status,
            bugs=int(by_metric.get("bugs", "0")),
            vulnerabilities=int(by_metric.get("vulnerabilities", "0")),
            code_smells=int(by_metric.get("code_smells", "0")),
            coverage=coverage,
            duplications=float(by_metric.get("duplicated_lines_density", "0")),
            dashboard_url=f"{sonar_url}/dashboard?id={project_key}",
            security_hotspots=int(by_metric.get("security_hotspots", "0")),
            ncloc=int(by_metric.get("ncloc", "0")),
        )
        if metrics.gate_status == "FAILED":
            metrics.issues = _fetch_sonar_issues(project_key, sonar_url, token)
        return metrics
    except Exception:
        logger.warning(
            "fetch_sonar_metrics failed for project_key=%s — returning None", project_key
        )
        return None


def _fetch_sonar_issues(project_key: str, sonar_url: str, token: str) -> list[SonarIssue]:
    """Fetch top BLOCKER/CRITICAL/MAJOR issues when quality gate fails. Never raises."""
    try:
        r = httpx.get(
            f"{sonar_url}/api/issues/search",
            params={
                "componentKeys": project_key,
                "resolved": "false",
                "severities": "BLOCKER,CRITICAL,MAJOR",
                "ps": 30,
                "s": "SEVERITY",
                "asc": "false",
            },
            auth=(token, ""),
            timeout=10.0,
        )
        r.raise_for_status()
        issues = []
        prefix = project_key + ":"
        for item in r.json().get("issues", []):
            component = item.get("component", "")
            file_path = component[len(prefix):] if component.startswith(prefix) else component
            issues.append(SonarIssue(
                file=file_path,
                line=item.get("line"),
                message=item.get("message", ""),
                severity=item.get("severity", ""),
                type=item.get("type", ""),
            ))
        return issues
    except Exception:
        logger.warning("_fetch_sonar_issues failed for project_key=%s", project_key)
        return []

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
                auth=(token, ""),  # SonarQube <10: token as basic-auth username
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
