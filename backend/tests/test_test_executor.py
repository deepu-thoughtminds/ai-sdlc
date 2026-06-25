"""Tests for services/test_executor.py — TESTEXEC-01, TESTEXEC-02.

All tests mock subprocess.run — no live Docker calls are made.

Coverage:
  detect_toolchain() — toolchain auto-detection from filesystem indicators.
  run_command()      — subprocess execution, timeout handling (T-23-02).
  run_static_analysis() — orchestration of detect_toolchain + run_command.

T-23-01 gate: every command produced by detect_toolchain is verified to be a
list — shell=True is structurally impossible when the command itself is a list
passed to subprocess.run().
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from services.test_executor import (
    TestResult,
    ToolchainCommand,
    detect_toolchain,
    run_command,
    run_static_analysis,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool_names(commands: list[ToolchainCommand]) -> list[str]:
    """Return list of tool names from a list of ToolchainCommand objects."""
    return [c.name for c in commands]


# ---------------------------------------------------------------------------
# detect_toolchain — Python project detection
# ---------------------------------------------------------------------------


def test_detect_toolchain_python_pyproject(tmp_path):
    """pyproject.toml present → ruff, mypy, bandit detected; no eslint."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    result = detect_toolchain(str(tmp_path))
    names = _tool_names(result)
    assert "ruff" in names
    assert "mypy" in names
    assert "bandit" in names
    assert "eslint" not in names


def test_detect_toolchain_python_setup_cfg(tmp_path):
    """setup.cfg present → ruff, mypy, bandit detected; no eslint."""
    (tmp_path / "setup.cfg").write_text("[metadata]\nname = mypackage\n")
    result = detect_toolchain(str(tmp_path))
    names = _tool_names(result)
    assert "ruff" in names
    assert "mypy" in names
    assert "bandit" in names
    assert "eslint" not in names


# ---------------------------------------------------------------------------
# detect_toolchain — JS/TS project detection
# ---------------------------------------------------------------------------


def test_detect_toolchain_js_package_json(tmp_path):
    """package.json + package-lock.json → eslint and npm_audit detected; no ruff."""
    (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    result = detect_toolchain(str(tmp_path))
    names = _tool_names(result)
    assert "eslint" in names
    assert "npm_audit" in names
    assert "ruff" not in names


def test_detect_toolchain_js_no_lockfile(tmp_path):
    """package.json without any lockfile → all JS tools skipped (can't npm ci)."""
    (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
    result = detect_toolchain(str(tmp_path))
    names = _tool_names(result)
    assert "eslint" not in names
    assert "npm_audit" not in names
    assert "tsc" not in names


def test_detect_toolchain_js_yarn_lock(tmp_path):
    """yarn.lock present → eslint and npm_audit detected using yarn commands."""
    (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n")
    result = detect_toolchain(str(tmp_path))
    names = _tool_names(result)
    assert "eslint" in names
    assert "npm_audit" in names
    # Verify yarn install is used, not npm ci
    eslint_cmd = next(c for c in result if c.name == "eslint")
    assert "yarn" in " ".join(eslint_cmd.command)


def test_detect_toolchain_ts_with_tsconfig(tmp_path):
    """package.json + package-lock.json + tsconfig.json → tsc detected."""
    (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}\n')
    result = detect_toolchain(str(tmp_path))
    names = _tool_names(result)
    assert "tsc" in names


def test_detect_toolchain_ts_without_tsconfig(tmp_path):
    """package.json + lockfile but no tsconfig.json → tsc NOT detected."""
    (tmp_path / "package.json").write_text('{"name": "myapp"}\n')
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    result = detect_toolchain(str(tmp_path))
    names = _tool_names(result)
    assert "tsc" not in names


def test_detect_toolchain_empty_workspace(tmp_path):
    """No indicator files → empty list returned."""
    result = detect_toolchain(str(tmp_path))
    assert result == []


# ---------------------------------------------------------------------------
# detect_toolchain — T-23-01 gate: every command is a list, not a string
# ---------------------------------------------------------------------------


def test_detect_toolchain_command_is_list_not_string(tmp_path):
    """T-23-01: every ToolchainCommand.command must be a list[str], never a str.

    When command is a list, subprocess.run() cannot use shell=True by accident.
    """
    # Create both Python and JS indicators to get full coverage.
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")
    (tmp_path / "package.json").write_text('{"name": "app"}\n')
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions": {}}\n')

    commands = detect_toolchain(str(tmp_path))
    assert commands, "Expected at least one command; got empty list"
    for cmd in commands:
        assert isinstance(cmd.command, list), (
            f"ToolchainCommand.command must be list; got {type(cmd.command)!r} "
            f"for tool={cmd.name!r}"
        )
        for token in cmd.command:
            assert isinstance(token, str), (
                f"All command tokens must be str; got {type(token)!r} "
                f"in command for tool={cmd.name!r}"
            )


# ---------------------------------------------------------------------------
# run_command — subprocess execution
# ---------------------------------------------------------------------------


def test_run_command_success():
    """Successful command → TestResult with returncode=0, timed_out=False."""
    cmd = ToolchainCommand(
        name="ruff",
        command=["docker", "run", "--rm", "qa-sandbox", "ruff", "check", "/workspace"],
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "All checks passed.\n"
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        result = run_command(cmd, timeout=30)

    mock_run.assert_called_once_with(
        cmd.command,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.tool == "ruff"
    assert result.returncode == 0
    assert result.stdout == "All checks passed.\n"
    assert result.timed_out is False


def test_run_command_failure():
    """Failing command → TestResult with non-zero returncode, timed_out=False."""
    cmd = ToolchainCommand(
        name="mypy",
        command=["docker", "run", "--rm", "qa-sandbox", "mypy", "/workspace"],
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = ""
    mock_proc.stderr = "error: Cannot find implementation\n"

    with patch("subprocess.run", return_value=mock_proc):
        result = run_command(cmd)

    assert result.tool == "mypy"
    assert result.returncode == 1
    assert result.timed_out is False
    assert "error" in result.stderr.lower()


def test_run_command_timeout():
    """TimeoutExpired → TestResult with returncode=-1, timed_out=True (T-23-02)."""
    cmd = ToolchainCommand(
        name="bandit",
        command=["docker", "run", "--rm", "qa-sandbox", "bandit", "-r", "/workspace"],
    )

    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd.command, 120)):
        result = run_command(cmd, timeout=120)

    assert result.tool == "bandit"
    assert result.returncode == -1
    assert result.timed_out is True
    assert "timed out" in result.stderr.lower()


def test_run_command_timeout_does_not_reraise():
    """TimeoutExpired is caught and does NOT propagate (T-23-02)."""
    cmd = ToolchainCommand(
        name="eslint",
        command=["docker", "run", "--rm", "qa-sandbox", "eslint", "/workspace"],
    )
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd.command, 60)):
        # Must not raise — returns TestResult instead
        result = run_command(cmd, timeout=60)

    assert result.timed_out is True


def test_run_command_non_timeout_exception_propagates():
    """Non-TimeoutExpired exceptions propagate to the caller (qa_pipeline handles them)."""
    cmd = ToolchainCommand(
        name="ruff",
        command=["docker", "run", "--rm", "qa-sandbox", "ruff", "check", "/workspace"],
    )
    with patch("subprocess.run", side_effect=OSError("Docker not found")):
        with pytest.raises(OSError, match="Docker not found"):
            run_command(cmd)


# ---------------------------------------------------------------------------
# run_static_analysis — orchestration
# ---------------------------------------------------------------------------


def test_run_static_analysis_python_project(tmp_path):
    """Python workspace → calls ruff, mypy, bandit via run_command; returns results."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = ""
    mock_proc.stderr = ""

    with patch("subprocess.run", return_value=mock_proc):
        results = run_static_analysis(str(tmp_path))

    names = [r.tool for r in results]
    assert "ruff" in names
    assert "mypy" in names
    assert "bandit" in names
    assert all(isinstance(r, TestResult) for r in results)


def test_run_static_analysis_empty_workspace(tmp_path):
    """No indicator files → returns empty list without calling subprocess."""
    with patch("subprocess.run") as mock_run:
        results = run_static_analysis(str(tmp_path))

    assert results == []
    mock_run.assert_not_called()


def test_run_static_analysis_returns_all_results_including_failures(tmp_path):
    """Even if a tool fails, run_static_analysis still returns results for ALL tools."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        proc = MagicMock()
        # First tool (ruff) fails; rest pass
        proc.returncode = 1 if call_count == 1 else 0
        proc.stdout = ""
        proc.stderr = "lint error" if call_count == 1 else ""
        return proc

    with patch("subprocess.run", side_effect=side_effect):
        results = run_static_analysis(str(tmp_path))

    assert len(results) == 3  # ruff, mypy, bandit
    assert results[0].returncode == 1
    assert results[1].returncode == 0


def test_run_static_analysis_timeout_continues(tmp_path):
    """If a tool times out, run_static_analysis continues with remaining tools."""
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n")

    call_count = 0

    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First tool (ruff) times out
            raise subprocess.TimeoutExpired(args[0], 120)
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc

    with patch("subprocess.run", side_effect=side_effect):
        results = run_static_analysis(str(tmp_path))

    assert results[0].timed_out is True   # ruff timed out
    assert results[1].timed_out is False   # mypy ran ok
