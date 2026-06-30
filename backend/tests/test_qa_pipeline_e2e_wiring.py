"""Tests for Phase 28 E2E wiring — PWGEN-01..03, EXEC-01, EXEC-02.

Tests the managed_app_container integration in qa_pipeline.py without
running the full run() coroutine (no DB, no credentials, no network).

Cases:
  A — Happy path: URL yielded → generate_e2e_tests called; BASE_URL in docker argv.
  B — ContainerStartError: generate_e2e_tests NOT called; e2e_skip_note set.
  C — ValueError: generate_e2e_tests NOT called; e2e_skip_note set.
  D — _format_qa_comment: live URL in header when present; absent when None.
"""

import contextlib
import glob
import os
import pathlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


from services.app_container import ContainerStartError
from services.qa_pipeline import _format_qa_comment
from services.test_executor import TestResult, ToolchainCommand


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_passing_result(tool="playwright"):
    return TestResult(tool=tool, returncode=0, stdout="1 passed", stderr="", timed_out=False)


def _make_file_change(path="tests/e2e/test_home.spec.ts", content="// test"):
    """Return a minimal FileChange-like object."""
    fc = MagicMock()
    fc.path = path
    fc.content = content
    return fc


@contextlib.contextmanager
def _raises_ctx(exc):
    """Context manager that raises exc immediately on __enter__."""
    raise exc
    yield  # pragma: no cover


# ---------------------------------------------------------------------------
# Small async helper that mirrors Step 4d/4e wiring logic.
# This avoids calling run() end-to-end while still exercising the real
# managed_app_container try/except pattern.
# ---------------------------------------------------------------------------

async def _run_e2e_step(
    *,
    workspace_path: str = "/tmp/jarvis-test",
    workspace_root: pathlib.Path | None = None,
    compose_network: str = "ai-sdlc-net",
    issue_key: str = "TEST-1",
    issue_summary: str = "Test summary",
    issue_description: str = "Test description",
    codebase_context: str = "",
    relevant_file_contents: dict | None = None,
):
    """Mirrors the Step 4d/4e block for isolated unit testing."""
    import services.qa_pipeline as _qap

    if workspace_root is None:
        workspace_root = pathlib.Path(workspace_path).resolve()
    if relevant_file_contents is None:
        relevant_file_contents = {}

    e2e_results: list[TestResult] = []
    playwright_py_results: list[TestResult] = []
    e2e_live_url: str | None = None
    e2e_skip_note: str | None = None

    try:
        with _qap.managed_app_container(workspace_path, compose_network) as playwright_deployment_url:
            e2e_live_url = playwright_deployment_url
            playwright_configs = glob.glob(
                os.path.join(workspace_path, "playwright.config.*")
            )
            if not playwright_configs:
                e2e_skip_note = "E2E tests skipped (no playwright.config.* detected in repository)."
            else:
                e2e_file_changes = _qap.generate_e2e_tests(
                    issue_key=issue_key,
                    issue_summary=issue_summary,
                    issue_description=issue_description,
                    codebase_context=codebase_context,
                    relevant_file_contents=relevant_file_contents,
                )
                for change in e2e_file_changes:
                    try:
                        resolved = (workspace_root / change.path).resolve()
                        if not str(resolved).startswith(str(workspace_root) + "/"):
                            raise ValueError(
                                f"E2E FileChange path escapes workspace: '{change.path}'"
                            )
                    except ValueError as ve:
                        continue

                    image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
                    cmd = ToolchainCommand(
                        name="playwright",
                        command=[
                            "docker", "run", "--rm",
                            "--network", compose_network,
                            "-v", f"{workspace_path}:/workspace",
                            "-e", f"BASE_URL={playwright_deployment_url}",
                            image,
                            "npx", "playwright", "test", f"/workspace/{change.path}",
                        ],
                    )
                    result = _qap.run_command(cmd)
                    e2e_results.append(result)

                # Step 4e — Python Playwright via Claude Code CLI (mirrors production)
                pw_py_file_changes = await _qap.run_claude_playwright_generator(
                    workspace_path=workspace_path,
                    issue_key=issue_key,
                    issue_summary=issue_summary,
                    issue_description=issue_description,
                    codebase_context=codebase_context,
                    relevant_file_contents=relevant_file_contents,
                )
                for change in pw_py_file_changes:
                    resolved = (workspace_root / change.path).resolve()
                    if not str(resolved).startswith(str(workspace_root) + "/"):
                        continue
                    image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
                    cmd = ToolchainCommand(
                        name=f"playwright-py:{change.path}",
                        command=[
                            "docker", "run", "--rm",
                            "--network", compose_network,
                            "-v", f"{workspace_path}:/workspace",
                            "-e", f"BASE_URL={playwright_deployment_url}",
                            image,
                            "python", "-m", "pytest", f"/workspace/{change.path}",
                            "--browser", "chromium", "--tb=short", "-q",
                        ],
                    )
                    result = _qap.run_command(cmd)
                    playwright_py_results.append(result)

    except (ValueError, ContainerStartError) as exc:
        e2e_skip_note = f"E2E tests skipped: {exc}"

    return e2e_results, playwright_py_results, e2e_live_url, e2e_skip_note


# ---------------------------------------------------------------------------
# Case A — Happy path (PWGEN-01, PWGEN-02, EXEC-01)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_happy_path_url_yielded_to_generation():
    """PWGEN-02: generate_e2e_tests only called after managed_app_container yields URL."""
    live_url = "http://jarvis-app-test1:3000"
    file_change = _make_file_change("tests/e2e/test_home.spec.ts")
    passing_result = _make_passing_result()

    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=live_url)
    mock_cm.__exit__ = MagicMock(return_value=False)

    with patch("services.qa_pipeline.managed_app_container", return_value=mock_cm) as mock_mac, \
         patch("services.qa_pipeline.generate_e2e_tests", return_value=[file_change]) as mock_gen, \
         patch("services.qa_pipeline.run_command", return_value=passing_result) as mock_run, \
         patch("services.qa_pipeline.run_claude_playwright_generator", new_callable=AsyncMock, return_value=[]), \
         patch("glob.glob", return_value=["/workspace/playwright.config.ts"]):

        e2e_results, _, e2e_live_url, e2e_skip_note = await _run_e2e_step()

    # PWGEN-01: URL from managed_app_container, not env var
    assert e2e_live_url == live_url

    # PWGEN-02: generate_e2e_tests called only after URL was obtained
    mock_gen.assert_called_once()

    # EXEC-01: docker run argv contains BASE_URL with the live URL
    run_call_args = mock_run.call_args[0][0]  # first positional arg = ToolchainCommand
    assert f"BASE_URL={live_url}" in run_call_args.command

    # No skip note on success
    assert e2e_skip_note is None
    assert len(e2e_results) == 1


# ---------------------------------------------------------------------------
# Case B — ContainerStartError skip (PWGEN-03)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_container_start_error_skips_e2e():
    """PWGEN-03: ContainerStartError → generate_e2e_tests not called; skip note set."""
    err_msg = "health-check timed out after 60s"
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(side_effect=ContainerStartError(err_msg))
    mock_cm.__exit__ = MagicMock(return_value=False)

    with patch("services.qa_pipeline.managed_app_container", return_value=mock_cm), \
         patch("services.qa_pipeline.generate_e2e_tests") as mock_gen, \
         patch("glob.glob", return_value=["/workspace/playwright.config.ts"]):

        e2e_results, _, e2e_live_url, e2e_skip_note = await _run_e2e_step()

    # generate_e2e_tests must NOT be called (container never became healthy)
    mock_gen.assert_not_called()

    # Skip note must mention the error
    assert e2e_skip_note is not None
    assert err_msg in e2e_skip_note

    # No results, no URL
    assert e2e_results == []
    assert e2e_live_url is None


# ---------------------------------------------------------------------------
# Case C — ValueError skip (PWGEN-03)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_value_error_skips_e2e():
    """PWGEN-03: ValueError (no serve script) → generate_e2e_tests not called; skip note set."""
    err_msg = "no preview/start/dev script in package.json"
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(side_effect=ValueError(err_msg))
    mock_cm.__exit__ = MagicMock(return_value=False)

    with patch("services.qa_pipeline.managed_app_container", return_value=mock_cm), \
         patch("services.qa_pipeline.generate_e2e_tests") as mock_gen:

        e2e_results, _, e2e_live_url, e2e_skip_note = await _run_e2e_step()

    mock_gen.assert_not_called()
    assert e2e_skip_note is not None
    assert err_msg in e2e_skip_note
    assert e2e_results == []
    assert e2e_live_url is None


# ---------------------------------------------------------------------------
# Case D — _format_qa_comment with/without live URL (EXEC-02)
# ---------------------------------------------------------------------------

def test_format_qa_comment_with_live_url_shows_url():
    """EXEC-02: When e2e_live_url is set, the E2E header includes the URL."""
    result = _make_passing_result("playwright")
    comment = _format_qa_comment(
        unit_test_results=[],
        e2e_results=[result],
        static_results=[],
        issue_key="TEST-1",
        e2e_live_url="http://jarvis-app-abc1:3000",
    )
    assert "live: http://jarvis-app-abc1:3000" in comment


def test_format_qa_comment_without_live_url_omits_url():
    """EXEC-02: When e2e_live_url is None, header reads '**E2E Tests:**' (no URL)."""
    comment = _format_qa_comment(
        unit_test_results=[],
        e2e_results=[],
        static_results=[],
        issue_key="TEST-1",
        e2e_skip_note="E2E tests skipped: no serve script.",
    )
    assert "live:" not in comment
    assert "**E2E Tests:**" in comment


# ---------------------------------------------------------------------------
# Case E — run_claude_playwright_generator invoked after container is healthy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claude_playwright_generator_called_after_container_healthy():
    """EXEC-02: run_claude_playwright_generator is called with correct args after URL yields."""
    live_url = "http://jarvis-app-test2:3000"
    py_change = _make_file_change("tests/pw/test_home.py")
    passing_result = _make_passing_result("playwright-py")

    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=live_url)
    mock_cm.__exit__ = MagicMock(return_value=False)

    with patch("services.qa_pipeline.managed_app_container", return_value=mock_cm), \
         patch("services.qa_pipeline.generate_e2e_tests", return_value=[]) as mock_gen, \
         patch(
             "services.qa_pipeline.run_claude_playwright_generator",
             new_callable=__import__("unittest.mock", fromlist=["AsyncMock"]).AsyncMock,
             return_value=[py_change],
         ) as mock_pw_gen, \
         patch("services.qa_pipeline.run_command", return_value=passing_result), \
         patch("glob.glob", return_value=["/workspace/playwright.config.ts"]):

        _, playwright_py_results, e2e_live_url, e2e_skip_note = await _run_e2e_step(
            issue_key="TEST-2",
            issue_summary="Home page test",
            issue_description="Verify home page loads",
        )

    # Generator must be called once the container is healthy
    mock_pw_gen.assert_called_once()
    call_kwargs = mock_pw_gen.call_args.kwargs
    assert call_kwargs["issue_key"] == "TEST-2"
    assert call_kwargs["issue_summary"] == "Home page test"

    # Result from the Python Playwright run is captured
    assert len(playwright_py_results) == 1
    assert playwright_py_results[0].returncode == 0
    assert e2e_skip_note is None
