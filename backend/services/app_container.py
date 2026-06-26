"""AppContainer service — SERVE-01..04.

Starts an ephemeral Docker container that builds and serves a cloned frontend
repo, health-polls until HTTP 200, and guarantees teardown in a finally block.

Design decisions:
- Subprocess-only (no Docker SDK); list-form argv only (no shell=True) — T-23-01.
- Context-manager API so teardown is co-located with the container lifecycle.
- Network-internal URL returned: http://<name>:<container_port> — reachable from
  the backend container and from sibling containers on ai-sdlc-net via Docker DNS.
  The host port (-p 0:PORT) is published for debugging only (SERVE-02).
- ponytail: container port defaults to 3000; Vite preview (4173) / dev (5173)
  apps need APP_CONTAINER_PORT override — single env knob, no per-framework matrix.

Threat mitigations:
  T-27-01: untrusted npm code runs in an unprivileged ephemeral container.
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

import httpx

logger = logging.getLogger(__name__)

_SERVE_PREFERENCE = ["preview", "start", "dev"]


class ContainerStartError(RuntimeError):
    """Raised when the target app container fails to start or become healthy."""


# ---------------------------------------------------------------------------
# SERVE-01 — serve command detection
# ---------------------------------------------------------------------------


def _detect_serve_command(workspace_path: str) -> tuple[str, dict]:
    """Return (serve_cmd, scripts) from package.json using preview>start>dev order.

    Raises ValueError when none of the preferred scripts are present.
    Raises ValueError when package.json is missing or unparseable.
    """
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
    """Return a sh -c script that installs, optionally builds, then serves.

    npm run build is included only when a build script exists (Vite/Next preview
    requires a prior build; plain dev does not).
    """
    parts = ["npm ci --no-audit --no-fund"]
    if "build" in scripts:
        parts.append("npm run build")
    # --host 0.0.0.0 binds all interfaces so the container is reachable from peers.
    parts.append(f"npm run {serve_cmd} -- --host 0.0.0.0 --port {container_port}")
    return " && ".join(parts)


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

    Yields the network-internal URL http://<name>:<container_port> after a
    successful HTTP 200 health-check. The container is always removed in the
    finally block regardless of how the context exits.

    Args:
        workspace_path:  Absolute path to the cloned repo (/tmp/jarvis-*).
        compose_network: Docker network name (e.g. ai-sdlc_ai-sdlc-net).
        container_port:  Port the app listens on inside the container (env default 3000).
        timeout_secs:    Health-check deadline in seconds (env default 60).
        image:           Docker image to use (env default qa-sandbox).
    """
    if container_port is None:
        container_port = int(os.environ.get("APP_CONTAINER_PORT", "3000"))
    if timeout_secs is None:
        timeout_secs = int(os.environ.get("APP_CONTAINER_HEALTH_TIMEOUT", "60"))
    if image is None:
        image = os.environ.get(
            "APP_CONTAINER_IMAGE",
            os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox"),
        )

    name = f"jarvis-app-{uuid.uuid4().hex[:8]}"
    started = False
    try:
        serve_cmd, scripts = _detect_serve_command(workspace_path)
        serve_script = _build_serve_script(serve_cmd, scripts, container_port)
        started = True
        _start_container(name, workspace_path, compose_network, container_port, image, serve_script)
        url = f"http://{name}:{container_port}"
        _wait_until_healthy(url, timeout_secs)
        logger.info("Container %s healthy at %s", name, url)
        yield url
    finally:
        if started:
            _remove_container(name)
