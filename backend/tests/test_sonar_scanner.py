"""Unit tests for services.sonar_scanner — SCAN-01..04, REPORT-01..03."""

import pathlib
from unittest.mock import MagicMock, patch

import httpx
import pytest

from services.sonar_scanner import _poll_ce_task, _read_ce_task_id, fetch_sonar_metrics, run_sonar_scan, SonarMetrics
from services.test_executor import TestResult


# ---------------------------------------------------------------------------
# _read_ce_task_id
# ---------------------------------------------------------------------------


def test_read_ce_task_id_missing_file():
    assert _read_ce_task_id("/nonexistent/path") is None


def test_read_ce_task_id_found(tmp_path):
    report_dir = tmp_path / ".scannerwork"
    report_dir.mkdir()
    (report_dir / "report-task.txt").write_text("ceTaskId=xyz789\nother=val", encoding="utf-8")
    assert _read_ce_task_id(str(tmp_path)) == "xyz789"


# ---------------------------------------------------------------------------
# run_sonar_scan — project key derivation (SCAN-02)
# ---------------------------------------------------------------------------


def test_project_key_derivation(tmp_path):
    fake_result = TestResult(
        tool="sonar-scanner", returncode=1, stdout="", stderr="docker not found", timed_out=False
    )
    with patch("services.sonar_scanner.run_command", return_value=fake_result) as mock_run:
        result = run_sonar_scan(
            workspace_path=str(tmp_path),
            project_key="acme__my-app",
            sonar_url="http://sonar:9000",
            token="tok",
            compose_network="net",
            timeout_secs=5,
        )
    assert result.returncode == 1
    cmd_list = mock_run.call_args[0][0].command
    assert "-Dsonar.projectKey=acme__my-app" in cmd_list
    assert "-Dsonar.projectName=acme/my-app" in cmd_list


# ---------------------------------------------------------------------------
# run_sonar_scan — non-zero exit returns immediately (SCAN-04)
# ---------------------------------------------------------------------------


def test_scanner_nonzero_returns_immediately(tmp_path):
    fake_result = TestResult(
        tool="sonar-scanner", returncode=2, stdout="", stderr="", timed_out=False
    )
    with patch("services.sonar_scanner.run_command", return_value=fake_result):
        with patch("services.sonar_scanner._poll_ce_task") as mock_poll:
            result = run_sonar_scan(
                workspace_path=str(tmp_path),
                project_key="org__repo",
                sonar_url="http://sonar:9000",
                token="tok",
                compose_network="net",
            )
    assert result.returncode == 2
    mock_poll.assert_not_called()


# ---------------------------------------------------------------------------
# run_sonar_scan — CE task success (SCAN-03)
# ---------------------------------------------------------------------------


def test_ce_task_success(tmp_path):
    # Create report-task.txt so _read_ce_task_id finds the task ID.
    sw = tmp_path / ".scannerwork"
    sw.mkdir()
    (sw / "report-task.txt").write_text("ceTaskId=abc123\n", encoding="utf-8")

    ok_result = TestResult(
        tool="sonar-scanner", returncode=0, stdout="scanner output", stderr="", timed_out=False
    )
    with patch("services.sonar_scanner.run_command", return_value=ok_result):
        with patch("services.sonar_scanner._poll_ce_task", return_value="SUCCESS"):
            result = run_sonar_scan(
                workspace_path=str(tmp_path),
                project_key="org__repo",
                sonar_url="http://sonar:9000",
                token="tok",
                compose_network="net",
            )
    assert result.returncode == 0
    assert "abc123" in result.stderr


# ---------------------------------------------------------------------------
# run_sonar_scan — CE task timeout (SCAN-03)
# ---------------------------------------------------------------------------


def test_ce_task_timeout(tmp_path):
    sw = tmp_path / ".scannerwork"
    sw.mkdir()
    (sw / "report-task.txt").write_text("ceTaskId=abc123\n", encoding="utf-8")

    ok_result = TestResult(
        tool="sonar-scanner", returncode=0, stdout="", stderr="", timed_out=False
    )
    with patch("services.sonar_scanner.run_command", return_value=ok_result):
        with patch("services.sonar_scanner._poll_ce_task", return_value="TIMEOUT"):
            result = run_sonar_scan(
                workspace_path=str(tmp_path),
                project_key="org__repo",
                sonar_url="http://sonar:9000",
                token="tok",
                compose_network="net",
            )
    assert result.returncode == 1
    assert result.timed_out is True


# ---------------------------------------------------------------------------
# _poll_ce_task
# ---------------------------------------------------------------------------


class TestCETaskPolling:
    def test_poll_returns_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"task": {"status": "SUCCESS"}}

        with patch("httpx.get", return_value=mock_resp):
            status = _poll_ce_task("http://sonar:9000", "tid", "tok", 30)
        assert status == "SUCCESS"

    def test_poll_returns_timeout(self):
        with patch("httpx.get", side_effect=httpx.RequestError("down")):
            with patch("time.sleep"):
                # timeout_secs=0 → deadline already past, loop exits immediately
                status = _poll_ce_task("http://sonar:9000", "tid", "tok", 0)
        assert status == "TIMEOUT"


# ---------------------------------------------------------------------------
# _run_sonar_step — SonarQube not ready produces non-None TestResult (SCAN-04)
# ---------------------------------------------------------------------------


def test_run_sonar_step_not_ready(monkeypatch):
    import sys
    from unittest.mock import MagicMock as _MagicMock

    # claude_agent_sdk is only present inside the Docker container; stub it so
    # qa_pipeline can be imported in a plain dev environment.
    if "claude_agent_sdk" not in sys.modules:
        _stub = _MagicMock()
        sys.modules["claude_agent_sdk"] = _stub

    from services.sonar_client import SonarQubeNotReadyError
    from services.qa_pipeline import _run_sonar_step

    monkeypatch.setenv("SONAR_URL", "http://sonar:9000")

    cloned = MagicMock()
    cloned.workspace_path = "/tmp/ws"
    cloned.owner = "acme"
    cloned.repo = "app"

    with patch("services.qa_pipeline.ensure_sonarqube_ready", side_effect=SonarQubeNotReadyError("not ready")):
        result = _run_sonar_step(cloned, "net", "PROJ-1")

    assert result is not None
    assert result.returncode != 0
    assert "not ready" in result.stderr


# ---------------------------------------------------------------------------
# fetch_sonar_metrics — REPORT-01..03
# ---------------------------------------------------------------------------

_HAPPY_MEASURES = [
    {"metric": "alert_status", "value": "OK"},
    {"metric": "bugs", "value": "3"},
    {"metric": "vulnerabilities", "value": "1"},
    {"metric": "code_smells", "value": "10"},
    {"metric": "coverage", "value": "82.5"},
    {"metric": "duplicated_lines_density", "value": "4.2"},
]


def _mock_sonar_response(measures=None, status_code=200, raise_on_status=False):
    """Build a MagicMock mimicking an httpx.Response for SonarQube measures API."""
    if measures is None:
        measures = _HAPPY_MEASURES
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {"component": {"measures": measures}}
    if raise_on_status:
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
    else:
        mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestFetchSonarMetrics:
    def test_happy_path_returns_sonar_metrics(self):
        """Valid measures JSON → SonarMetrics with correct field values."""
        mock_resp = _mock_sonar_response()
        with patch("httpx.get", return_value=mock_resp):
            result = fetch_sonar_metrics("myorg__myapp", "http://sonar:9000", "tok")

        assert isinstance(result, SonarMetrics)
        assert result.gate_status == "PASSED"
        assert result.bugs == 3
        assert result.vulnerabilities == 1
        assert result.code_smells == 10
        assert result.coverage == pytest.approx(82.5)
        assert result.duplications == pytest.approx(4.2)
        assert result.dashboard_url == "http://sonar:9000/dashboard?id=myorg__myapp"

    def test_alert_status_error_maps_to_failed(self):
        """alert_status ERROR in response → gate_status FAILED."""
        measures = list(_HAPPY_MEASURES)
        measures[0] = {"metric": "alert_status", "value": "ERROR"}
        mock_resp = _mock_sonar_response(measures=measures)
        with patch("httpx.get", return_value=mock_resp):
            result = fetch_sonar_metrics("org__repo", "http://sonar:9000", "tok")

        assert result is not None
        assert result.gate_status == "FAILED"

    def test_coverage_absent_returns_none(self):
        """Measures list missing 'coverage' metric → SonarMetrics.coverage is None."""
        measures = [m for m in _HAPPY_MEASURES if m["metric"] != "coverage"]
        mock_resp = _mock_sonar_response(measures=measures)
        with patch("httpx.get", return_value=mock_resp):
            result = fetch_sonar_metrics("org__repo", "http://sonar:9000", "tok")

        assert result is not None
        assert result.coverage is None

    def test_request_error_returns_none(self):
        """httpx.RequestError raised → returns None, never raises."""
        with patch("httpx.get", side_effect=httpx.RequestError("network down")):
            result = fetch_sonar_metrics("org__repo", "http://sonar:9000", "tok")

        assert result is None

    def test_http_500_returns_none(self):
        """HTTP 500 (raise_for_status raises) → returns None, never raises."""
        mock_resp = _mock_sonar_response(raise_on_status=True)
        with patch("httpx.get", return_value=mock_resp):
            result = fetch_sonar_metrics("org__repo", "http://sonar:9000", "tok")

        assert result is None

    def test_missing_component_key_returns_none(self):
        """Response JSON without 'component' key → returns None, never raises."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"error": "not found"}
        with patch("httpx.get", return_value=mock_resp):
            result = fetch_sonar_metrics("org__repo", "http://sonar:9000", "tok")

        assert result is None

    def test_dashboard_url_format(self):
        """Dashboard URL uses {sonar_url}/dashboard?id={project_key} format."""
        mock_resp = _mock_sonar_response()
        with patch("httpx.get", return_value=mock_resp):
            result = fetch_sonar_metrics("acme__myapp", "http://sonar:9000", "tok")

        assert result is not None
        assert result.dashboard_url == "http://sonar:9000/dashboard?id=acme__myapp"
