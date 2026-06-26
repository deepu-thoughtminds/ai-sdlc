"""AppContainer service — SERVE-01..04.

Starts an ephemeral Docker container that builds and serves a cloned repo,
health-polls until HTTP 200, and guarantees teardown in a finally block.

Supported stacks (auto-detected from workspace):
  npm/TypeScript — package.json with preview/start/dev script
  Python         — requirements.txt / pyproject.toml / Procfile / app.py / main.py
  (unknown stack raises ValueError with guidance)

Design decisions:
- Subprocess-only (no Docker SDK); list-form argv only (no shell=True) — T-23-01.
- Context-manager API so teardown is co-located with the container lifecycle.
- Network-internal URL returned: http://<name>:<container_port> — reachable from
  the backend container and from sibling containers on ai-sdlc-net via Docker DNS.
  The host port (-p 0:PORT) is published for debugging only (SERVE-02).
- ponytail: container port defaults to 3000; override per-stack via APP_CONTAINER_PORT.

Threat mitigations:
  T-27-01: untrusted code runs in an unprivileged ephemeral container.
  T-27-02: health-check deadline (APP_CONTAINER_HEALTH_TIMEOUT) raises ContainerStartError.
  T-27-03: docker rm -f in finally + --rm on docker run covers both paths.
  T-27-04: served container joins ai-sdlc-net but receives no credentials.
  T-27-05: list-form argv + uuid-derived container name (no external input).
"""

import contextlib
import json
import logging
import os
import pathlib
import subprocess
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_SERVE_PREFERENCE = ["preview", "start", "dev"]

_DEFAULT_NPM_IMAGE = "qa-sandbox"
_DEFAULT_PYTHON_IMAGE = "python:3.12-slim"


class ContainerStartError(RuntimeError):
    """Raised when the target app container fails to start or become healthy."""


@dataclass
class StackInfo:
    stack: str          # "npm" | "python"
    serve_script: str   # sh -c argument
    image: str
    container_port: int


# ---------------------------------------------------------------------------
# SERVE-01 — serve command detection (npm helper, kept for direct test coverage)
# ---------------------------------------------------------------------------


def _detect_serve_command(workspace_path: str) -> tuple[str, dict]:
    """Return (serve_cmd, scripts) from package.json using preview>start>dev order."""
    pkg_path = pathlib.Path(workspace_path) / "package.json"
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    scripts: dict = data.get("scripts", {})
    for key in _SERVE_PREFERENCE:
        if key in scripts:
            logger.info("Detected serve command: %s (from package.json)", key)
            return key, scripts
    raise ValueError(
        f"No serve script found in package.json (checked {_SERVE_PREFERENCE})"
    )


# ---------------------------------------------------------------------------
# SERVE-02 — container start
# ---------------------------------------------------------------------------


def _build_serve_script(serve_cmd: str, scripts: dict, container_port: int) -> str:
    """Return a sh -c script that installs, optionally builds, then serves (npm)."""
    parts = ["npm ci --no-audit --no-fund"]
    if "build" in scripts:
        parts.append("npm run build")
    # --host 0.0.0.0 binds all interfaces so the container is reachable from peers.
    parts.append(f"npm run {serve_cmd} -- --host 0.0.0.0 --port {container_port}")
    return " && ".join(parts)


def _detect_python_entry(ws: pathlib.Path, container_port: int) -> str:
    """Return a sh -c script to install deps and serve a Python app.

    Detection order:
      1. Procfile  web: line
      2. pyproject.toml with fastapi/flask/uvicorn dep → uvicorn main:app
      3. main.py / app.py existence → uvicorn <module>:app or python <file>
      4. requirements.txt only → raise ValueError
    """
    install = "pip install --no-cache-dir -r requirements.txt"
    if not (ws / "requirements.txt").exists():
        # Try pyproject.toml install
        install = "pip install --no-cache-dir ."

    # 1. Procfile
    procfile = ws / "Procfile"
    if procfile.exists():
        for line in procfile.read_text(encoding="utf-8").splitlines():
            if line.startswith("web:"):
                cmd = line[4:].strip()
                # Inject host/port for uvicorn/gunicorn if not already present
                if "uvicorn" in cmd and "--port" not in cmd:
                    cmd += f" --host 0.0.0.0 --port {container_port}"
                logger.info("Python serve command from Procfile: %s", cmd)
                return f"{install} && {cmd}"

    # 2. pyproject.toml — check for web framework deps
    pyproject = ws / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text(encoding="utf-8").lower()
        if "uvicorn" in content or "fastapi" in content:
            entry = "main:app" if (ws / "main.py").exists() else "app:app"
            cmd = f"uvicorn {entry} --host 0.0.0.0 --port {container_port}"
            logger.info("Python serve command (uvicorn from pyproject.toml): %s", cmd)
            return f"{install} && {cmd}"
        if "flask" in content:
            cmd = f"flask run --host 0.0.0.0 --port {container_port}"
            logger.info("Python serve command (flask from pyproject.toml): %s", cmd)
            return f"{install} && {cmd}"

    # 3. main.py / app.py presence
    for candidate in ("main.py", "app.py"):
        if (ws / candidate).exists():
            module = candidate[:-3]  # strip .py
            # Assume uvicorn-style if file contains "app" or "application" FastAPI/Starlette
            cmd = f"uvicorn {module}:app --host 0.0.0.0 --port {container_port}"
            logger.info("Python serve command (fallback uvicorn %s): %s", candidate, cmd)
            return f"{install} && {cmd}"

    raise ValueError(
        "Python project detected but no serve entry point found. "
        "Add a Procfile with a 'web:' line, or ensure main.py/app.py exists."
    )


def _detect_stack(workspace_path: str, container_port: int, npm_image: str, python_image: str) -> StackInfo:
    """Auto-detect project stack and return StackInfo with serve script + image."""
    ws = pathlib.Path(workspace_path)

    # npm / TypeScript — package.json wins if it has a serve script
    if (ws / "package.json").exists():
        try:
            serve_cmd, scripts = _detect_serve_command(workspace_path)
            script = _build_serve_script(serve_cmd, scripts, container_port)
            logger.info("Stack detected: npm")
            return StackInfo(stack="npm", serve_script=script, image=npm_image, container_port=container_port)
        except ValueError:
            pass  # package.json exists but no serve script — fall through

    # Python — requirements.txt or pyproject.toml
    if (ws / "requirements.txt").exists() or (ws / "pyproject.toml").exists():
        script = _detect_python_entry(ws, container_port)
        logger.info("Stack detected: python")
        return StackInfo(stack="python", serve_script=script, image=python_image, container_port=container_port)

    raise ValueError(
        f"Cannot detect project stack in {workspace_path}. "
        "Expected package.json (npm), requirements.txt, or pyproject.toml (Python)."
    )


def _start_container(
    name: str,
    workspace_path: str,
    compose_network: str,
    container_port: int,
    image: str,
    serve_script: str,
) -> str:
    """Start a detached container and return its container ID.

    Raises ContainerStartError on non-zero docker run exit.
    """
    argv = [
        "docker", "run", "-d", "--rm",
        "--name", name,
        "--network", compose_network,
        "-p", f"0:{container_port}",
        "-v", f"{workspace_path}:/app",
        "-w", "/app",
        image,
        "sh", "-c", serve_script,
    ]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise ContainerStartError(
            f"docker run failed (exit {proc.returncode}): {proc.stderr[:500]}"
        )
    container_id = proc.stdout.strip()
    # Log the dynamically assigned host port for traceability (best-effort).
    try:
        inspect = subprocess.run(
            ["docker", "inspect", container_id,
             "--format", "{{json .NetworkSettings.Ports}}"],
            capture_output=True, text=True, timeout=10,
        )
        if inspect.returncode == 0:
            logger.debug("Container %s ports: %s", name, inspect.stdout.strip())
    except Exception:  # noqa: BLE001
        pass
    return container_id


# ---------------------------------------------------------------------------
# SERVE-03 — health-check polling
# ---------------------------------------------------------------------------


def _wait_until_healthy(url: str, timeout_secs: int) -> None:
    """Poll GET url until HTTP 200 or deadline. Raises ContainerStartError on timeout."""
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=5.0)
            if r.status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(2)
    raise ContainerStartError(
        f"App did not become healthy within {timeout_secs}s at {url}"
    )


# ---------------------------------------------------------------------------
# SERVE-04 — teardown helper (never raises)
# ---------------------------------------------------------------------------


def _remove_container(name: str) -> None:
    """Remove the container via docker rm -f. Never propagates exceptions."""
    try:
        proc = subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            logger.debug("docker rm -f %s exited %d: %s", name, proc.returncode, proc.stderr)
    except Exception:  # noqa: BLE001
        logger.debug("docker rm -f %s failed (suppressed)", name)


# ---------------------------------------------------------------------------
# Public API — SERVE-02..04 assembly
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def managed_app_container(
    workspace_path: str,
    compose_network: str,
    *,
    container_port: int | None = None,
    timeout_secs: int | None = None,
    image: str | None = None,
) -> Iterator[str]:
    """Context manager that builds, serves, and tears down an app container.

    Auto-detects project stack (npm/TypeScript, Python) and picks the correct
    Docker image and startup script. Yields the network-internal URL
    http://<name>:<container_port> after a successful HTTP 200 health-check.
    The container is always removed in the finally block.

    Args:
        workspace_path:  Absolute path to the cloned repo (/tmp/jarvis-*).
        compose_network: Docker network name (e.g. ai-sdlc_ai-sdlc-net).
        container_port:  Port the app listens on inside the container (env default 3000).
        timeout_secs:    Health-check deadline in seconds (env default 60).
        image:           Override Docker image (skips per-stack default selection).
    """
    if container_port is None:
        container_port = int(os.environ.get("APP_CONTAINER_PORT", "3000"))
    if timeout_secs is None:
        timeout_secs = int(os.environ.get("APP_CONTAINER_HEALTH_TIMEOUT", "60"))

    npm_image = os.environ.get("APP_CONTAINER_IMAGE", os.environ.get("QA_SANDBOX_IMAGE", _DEFAULT_NPM_IMAGE))
    python_image = os.environ.get("APP_CONTAINER_PYTHON_IMAGE", _DEFAULT_PYTHON_IMAGE)

    name = f"jarvis-app-{uuid.uuid4().hex[:8]}"
    started = False
    try:
        stack_info = _detect_stack(workspace_path, container_port, npm_image, python_image)
        effective_image = image or stack_info.image
        started = True
        _start_container(name, workspace_path, compose_network, stack_info.container_port, effective_image, stack_info.serve_script)
        url = f"http://{name}:{stack_info.container_port}"
        _wait_until_healthy(url, timeout_secs)
        logger.info("Container %s healthy at %s (stack=%s)", name, url, stack_info.stack)
        yield url
    finally:
        if started:
            _remove_container(name)
