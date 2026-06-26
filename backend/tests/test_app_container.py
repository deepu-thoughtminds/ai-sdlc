"""Unit tests for services.app_container — SERVE-01..04.

All tests mock subprocess.run and httpx.get — no Docker daemon, no network,
no real sleep required.

Coverage:
- SERVE-01: _detect_serve_command prefers preview>start>dev, raises ValueError when absent.
- SERVE-02: docker run argv is list-form with correct flags; non-zero exit raises ContainerStartError.
- SERVE-03: _wait_until_healthy returns on 200, raises ContainerStartError when deadline passes.
- SERVE-04: managed_app_container calls docker rm -f on success, ContainerStartError, arbitrary
            exception; does NOT call docker rm -f when _detect_serve_command raises ValueError.
"""

import json
import subprocess
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from services.app_container import (
    ContainerStartError,
    _build_serve_script,
    _detect_serve_command,
    _remove_container,
    _start_container,
    _wait_until_healthy,
    managed_app_container,
)

# ---------------------------------------------------------------------------
# SERVE-01 — _detect_serve_command
# ---------------------------------------------------------------------------

_PKG_PREVIEW_START = json.dumps({"scripts": {"preview": "vite preview", "start": "node server.js"}})
_PKG_START_ONLY = json.dumps({"scripts": {"start": "node server.js"}})
_PKG_DEV_ONLY = json.dumps({"scripts": {"dev": "vite"}})
_PKG_NO_SERVE = json.dumps({"scripts": {"build": "vite build", "test": "vitest"}})
_PKG_EMPTY = json.dumps({})


def test_detect_serve_command_prefers_preview():
    with patch("pathlib.Path.read_text", return_value=_PKG_PREVIEW_START):
        cmd, scripts = _detect_serve_command("/workspace")
    assert cmd == "preview"
    assert "preview" in scripts


def test_detect_serve_command_falls_back_to_start():
    with patch("pathlib.Path.read_text", return_value=_PKG_START_ONLY):
        cmd, _ = _detect_serve_command("/workspace")
    assert cmd == "start"


def test_detect_serve_command_falls_back_to_dev():
    with patch("pathlib.Path.read_text", return_value=_PKG_DEV_ONLY):
        cmd, _ = _detect_serve_command("/workspace")
    assert cmd == "dev"


def test_detect_serve_command_raises_when_absent():
    with patch("pathlib.Path.read_text", return_value=_PKG_NO_SERVE):
        with pytest.raises(ValueError, match="No serve script"):
            _detect_serve_command("/workspace")


def test_detect_serve_command_raises_on_empty_scripts():
    with patch("pathlib.Path.read_text", return_value=_PKG_EMPTY):
        with pytest.raises(ValueError):
            _detect_serve_command("/workspace")


# ---------------------------------------------------------------------------
# _build_serve_script
# ---------------------------------------------------------------------------


def test_build_serve_script_includes_build_when_present():
    scripts = {"preview": "vite preview", "build": "vite build"}
    script = _build_serve_script("preview", scripts, 3000)
    assert "npm run build" in script
    assert "npm run preview" in script
    assert "--host 0.0.0.0" in script


def test_build_serve_script_omits_build_when_absent():
    scripts = {"dev": "vite"}
    script = _build_serve_script("dev", scripts, 3000)
    assert "npm run build" not in script
    assert "npm run dev" in script


# ---------------------------------------------------------------------------
# SERVE-02 — _start_container (docker run argv)
# ---------------------------------------------------------------------------


def _make_proc(returncode=0, stdout="abc123\n", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_start_container_argv_contains_required_flags():
    """docker run argv must include -d, --rm, --network, -p 0:PORT, -v ws:/app."""
    captured_argv = []

    def fake_run(argv, **kw):
        captured_argv.extend(argv)
        return _make_proc()

    with patch("subprocess.run", side_effect=fake_run):
        _start_container(
            name="jarvis-app-test",
            workspace_path="/tmp/jarvis-ws",
            compose_network="ai-sdlc-net",
            container_port=3000,
            image="qa-sandbox",
            serve_script="npm run dev",
        )

    assert "-d" in captured_argv
    assert "--rm" in captured_argv
    assert "--network" in captured_argv
    assert "ai-sdlc-net" in captured_argv
    assert "-p" in captured_argv
    assert "0:3000" in captured_argv
    assert "-v" in captured_argv
    assert "/tmp/jarvis-ws:/app" in captured_argv
    assert "qa-sandbox" in captured_argv


def test_start_container_nonzero_exit_raises():
    with patch("subprocess.run", return_value=_make_proc(returncode=1, stderr="pull failed")):
        with pytest.raises(ContainerStartError, match="docker run failed"):
            _start_container("n", "/ws", "net", 3000, "img", "script")


def test_start_container_returns_container_id():
    with patch("subprocess.run", return_value=_make_proc(stdout="deadbeef\n")):
        cid = _start_container("n", "/ws", "net", 3000, "img", "script")
    assert cid == "deadbeef"


# ---------------------------------------------------------------------------
# SERVE-03 — _wait_until_healthy
# ---------------------------------------------------------------------------


def _make_httpx_response(status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    return resp


def test_wait_until_healthy_returns_on_200():
    with patch("httpx.get", return_value=_make_httpx_response(200)):
        with patch("time.sleep"):
            _wait_until_healthy("http://app:3000", timeout_secs=10)


def test_wait_until_healthy_ignores_non_200():
    """Non-200 responses don't return — loop continues until deadline."""
    call_count = {"n": 0}

    monotonic_values = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 100.0]  # deadline=5s
    mono_iter = iter(monotonic_values)

    def fake_monotonic():
        return next(mono_iter)

    def fake_get(url, **kw):
        call_count["n"] += 1
        return _make_httpx_response(503)

    with patch("time.monotonic", side_effect=fake_monotonic):
        with patch("httpx.get", side_effect=fake_get):
            with patch("time.sleep"):
                with pytest.raises(ContainerStartError, match="healthy"):
                    _wait_until_healthy("http://app:3000", timeout_secs=5)


def test_wait_until_healthy_swallows_request_error():
    """httpx.RequestError is swallowed and the loop continues."""
    monotonic_values = [0.0, 1.0, 2.0, 100.0]
    mono_iter = iter(monotonic_values)

    def fake_get(url, **kw):
        raise httpx.RequestError("connection refused")

    with patch("time.monotonic", side_effect=lambda: next(mono_iter)):
        with patch("httpx.get", side_effect=fake_get):
            with patch("time.sleep"):
                with pytest.raises(ContainerStartError):
                    _wait_until_healthy("http://app:3000", timeout_secs=5)


def test_wait_until_healthy_raises_on_timeout():
    with patch("time.monotonic", side_effect=[0.0, 100.0]):
        with patch("httpx.get", side_effect=httpx.RequestError("refused")):
            with patch("time.sleep"):
                with pytest.raises(ContainerStartError, match="healthy"):
                    _wait_until_healthy("http://app:3000", timeout_secs=5)


# ---------------------------------------------------------------------------
# _remove_container
# ---------------------------------------------------------------------------


def test_remove_container_calls_docker_rm_f():
    with patch("subprocess.run", return_value=_make_proc()) as mock_run:
        _remove_container("jarvis-app-abc")
    mock_run.assert_called_once()
    argv = mock_run.call_args[0][0]
    assert argv == ["docker", "rm", "-f", "jarvis-app-abc"]


def test_remove_container_never_raises_on_failure():
    with patch("subprocess.run", side_effect=Exception("boom")):
        _remove_container("jarvis-app-abc")  # must not raise


# ---------------------------------------------------------------------------
# SERVE-04 — managed_app_container teardown guarantees
# ---------------------------------------------------------------------------


def _patch_stack(pkg_json=_PKG_DEV_ONLY):
    """Return a context-manager stack that patches subprocess.run and httpx.get."""
    return [
        patch("pathlib.Path.read_text", return_value=pkg_json),
        patch("time.sleep"),
        patch("httpx.get", return_value=_make_httpx_response(200)),
    ]


def _make_subprocess_side_effect(container_name_holder):
    """Returns a side_effect for subprocess.run.

    - docker run → success (stdout = container_id_stub)
    - docker rm -f → success (stdout = "")
    - docker inspect → treated as best-effort (returncode 0, empty stdout)
    """
    def side_effect(argv, **kw):
        if argv and argv[1] == "run":
            # Capture the container name from --name arg for assertion use.
            try:
                idx = argv.index("--name")
                container_name_holder["name"] = argv[idx + 1]
            except (ValueError, IndexError):
                pass
            return _make_proc(stdout="stub-container-id\n")
        if argv and argv[1] == "inspect":
            return _make_proc(stdout="{}")
        if argv and argv[1] == "rm":
            container_name_holder["rm_called"] = True
            container_name_holder["rm_argv"] = list(argv)
            return _make_proc()
        return _make_proc()

    return side_effect


def test_managed_app_container_success_then_removes():
    """Happy path: yields URL, removes container on exit."""
    holder = {"rm_called": False}
    with patch("pathlib.Path.read_text", return_value=_PKG_DEV_ONLY):
        with patch("subprocess.run", side_effect=_make_subprocess_side_effect(holder)):
            with patch("httpx.get", return_value=_make_httpx_response(200)):
                with patch("time.sleep"):
                    with managed_app_container("/ws", "net") as url:
                        assert "http://" in url
    assert holder["rm_called"], "docker rm -f should be called after success"
    assert "-f" in holder["rm_argv"]


def test_managed_app_container_removes_on_container_start_error():
    """ContainerStartError during health-check still calls docker rm -f."""
    holder = {"rm_called": False}

    def health_fail(*a, **kw):
        raise httpx.RequestError("refused")

    monotonic_values = [0.0, 100.0]
    mono_iter = iter(monotonic_values)

    with patch("pathlib.Path.read_text", return_value=_PKG_DEV_ONLY):
        with patch("subprocess.run", side_effect=_make_subprocess_side_effect(holder)):
            with patch("httpx.get", side_effect=health_fail):
                with patch("time.sleep"):
                    with patch("time.monotonic", side_effect=lambda: next(mono_iter)):
                        with pytest.raises(ContainerStartError):
                            with managed_app_container("/ws", "net", timeout_secs=5):
                                pass

    assert holder["rm_called"], "docker rm -f must run even after ContainerStartError"


def test_managed_app_container_removes_on_arbitrary_exception():
    """Exception raised inside the with-body still triggers docker rm -f."""
    holder = {"rm_called": False}
    with patch("pathlib.Path.read_text", return_value=_PKG_DEV_ONLY):
        with patch("subprocess.run", side_effect=_make_subprocess_side_effect(holder)):
            with patch("httpx.get", return_value=_make_httpx_response(200)):
                with patch("time.sleep"):
                    with pytest.raises(RuntimeError, match="boom"):
                        with managed_app_container("/ws", "net") as url:
                            raise RuntimeError("boom")

    assert holder["rm_called"], "docker rm -f must run even when body raises"


def test_managed_app_container_no_rm_when_detect_fails():
    """ValueError from _detect_serve_command → container never started → no docker rm -f."""
    rm_calls = []

    def fake_subprocess(argv, **kw):
        if argv and argv[1] == "rm":
            rm_calls.append(argv)
        return _make_proc()

    with patch("pathlib.Path.read_text", return_value=_PKG_NO_SERVE):
        with patch("subprocess.run", side_effect=fake_subprocess):
            with pytest.raises(ValueError, match="No serve script"):
                with managed_app_container("/ws", "net"):
                    pass

    assert rm_calls == [], "docker rm -f must NOT be called when no container was started"
