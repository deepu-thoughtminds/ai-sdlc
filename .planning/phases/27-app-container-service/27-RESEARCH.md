# Phase 27: App Container Service — Research

**Researched**: 2026-06-26
**Researcher**: gsd-phase-researcher

## Summary

Phase 27 introduces `app_container.py`, a new backend service that starts a cloned target app in a short-lived Docker container, confirms it is reachable, and always tears it down. The existing codebase uses `subprocess`-based `docker run --rm` throughout — there is no Docker Python SDK usage anywhere. The compose network is named `ai-sdlc-net` (bare) in `docker-compose.yml` but prefixed at runtime (e.g. `ai-sdlc_ai-sdlc-net`); `_resolve_compose_network()` in `qa_pipeline.py` already handles this discovery and must be reused. `httpx` is already installed and used across the backend; it is the correct tool for health-check polling. No new dependencies are required.

**Primary recommendation:** Implement `app_container.py` as a plain Python module with one public function `serve_app(workspace_path, compose_network) -> str` that encapsulates container start, health-check, and teardown-in-finally. Mirror the subprocess-only, no-SDK, no-shell=True patterns used by every existing service.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SERVE-01 | Detect serve command from `package.json` scripts (`preview` > `start` > `dev`) | `json.loads` + `pathlib.Path.read_text` on `package.json`; ordered lookup |
| SERVE-02 | Build and serve app in ephemeral Docker container on compose network, dynamic host port | `docker run -d -p 0:PORT --network <net>` then `docker inspect` for assigned port |
| SERVE-03 | Poll `GET /` until HTTP 200 or timeout (default 60 s), raise `ContainerStartError` on timeout | `httpx.get` in a `time.sleep` loop; `httpx` already installed |
| SERVE-04 | Container torn down in `finally` block on all exit paths | `docker rm -f <container_id>` in `finally`; mirrors T-23-03 pattern |
</phase_requirements>

---

## Existing Codebase Patterns

### Docker Compose & Network Setup

`docker-compose.yml` declares the network as:

```yaml
networks:
  ai-sdlc-net:
    driver: bridge
```

All services (`backend`, `frontend`, `qa-sandbox`, `freellmapi`, `litellm`, `hermes`, `mcp-atlassian`) attach to this network. At runtime Docker Compose prefixes the project name, producing names like `ai-sdlc_ai-sdlc-net` or `thoughtminds_projects_ai-sdlc_ai-sdlc-net`.

The `backend` container mounts `/var/run/docker.sock` and has `docker-cli` installed — it can issue `docker` commands against the host daemon.

### Current QA Pipeline (qa_pipeline.py)

`_resolve_compose_network()` (lines 80–118) already solves the network-name discovery problem:
1. Checks `COMPOSE_NETWORK` env var override
2. Inspects own container's networks via `docker inspect $(hostname)` for a name ending `_ai-sdlc-net`
3. Falls back to `docker network ls --filter name=ai-sdlc-net` picking the shortest match
4. Final fallback: bare string `"ai-sdlc-net"`

This function is called for every Playwright container run. Phase 27 must reuse it, not re-implement it.

Existing Docker container usage pattern in `qa_pipeline.py` / `test_executor.py`:
- All Docker calls use `subprocess.run(["docker", "run", "--rm", ...], ...)` — list-form args, `shell=False` (enforced by T-23-01)
- Containers are ephemeral: `--rm` flag on every `docker run`
- No `docker start` / long-running containers in any existing service

Workspace cleanup pattern (T-23-03, lines 560–564):
```python
finally:
    if cloned is not None:
        shutil.rmtree(cloned.workspace_path, ignore_errors=True)
```

Phase 27 container teardown must mirror this exactly.

### Python Docker SDK Usage

**None.** The entire backend uses `subprocess.run(["docker", ...])` exclusively. `docker` Python SDK is not in `requirements.txt`. This is intentional: the backend image installs `docker-cli` (not the SDK) in its `Dockerfile`:

```
RUN apt-get install -y --no-install-recommends git nodejs npm docker-cli
```

Stick with subprocess — it is the established, audited pattern.

### Service Patterns

All backend services follow these conventions:
- **Module-level logger**: `logger = logging.getLogger(__name__)`
- **Dataclass results**: `@dataclass` for structured return values (see `ClonedRepo`, `TestResult`, `PullRequest`)
- **Specific exceptions**: `ValueError` for bad input, `RuntimeError` for subprocess failures
- **No `shell=True`**: enforced project-wide; use list-form args
- **`timeout=` on every `subprocess.run`**: prevents hanging
- **Security scrubbing**: tokens replaced with `"***"` before appearing in any log
- **Async only at pipeline level**: individual service functions are synchronous; `async` only in pipeline orchestrators (`qa_pipeline.run`, `dev_pipeline.run`)

`ContainerStartError` should be a new exception class defined in `app_container.py` (not a generic `RuntimeError`) so callers can distinguish container-specific failures from other `RuntimeError` sources.

### Repo Cloning

`repo_clone.py` uses `tempfile.mkdtemp(prefix=f"jarvis-{owner}-{repo}-")` which writes to `/tmp`. The `docker-compose.yml` mounts `/tmp:/tmp` on the backend container so workspace paths are visible to the host Docker daemon. This means volume mounts like `-v {workspace_path}:/workspace` work correctly in `docker run` commands even though `workspace_path` is inside `/tmp` on the backend container.

The cloned repo lands at e.g. `/tmp/jarvis-acme-my-app-XXXX/`. `package.json` will be at `{workspace_path}/package.json`.

---

## Technical Decisions

### Docker Python SDK vs subprocess

**Use subprocess.** No Docker SDK is installed, no SDK usage exists anywhere, and adding it would be the first new dependency in the backend since `claude-agent-sdk`. The subprocess pattern is already proven, audited (T-23-01), and sufficient for `docker run -d`, `docker inspect`, and `docker rm -f`. `[ASSUMED]` SDK would add ~5 MB and a new dependency for zero functional gain here.

### Network attachment approach

Call `_resolve_compose_network()` from `qa_pipeline.py` — it already handles all discovery cases. The caller (`qa_pipeline.py`) passes the resolved network name into `serve_app()`. Do not duplicate the discovery logic.

```python
# in qa_pipeline.py (caller)
from services.app_container import serve_app, ContainerStartError
compose_network = _resolve_compose_network()
live_url = serve_app(workspace_path, compose_network)
```

### Port allocation

Use `docker run -d -p 0:3000 ...` — Docker allocates a random ephemeral host port. Then call `docker inspect <container_id> --format '{{json .NetworkSettings.Ports}}'` to read the assigned host port. This avoids all port-conflict risks and requires no `socket.bind(0)` tricks.

The container port to expose (default `3000`) should be configurable via a constant or parameter — Next.js/Vite/Create React App all default to `3000`; Vite preview defaults to `4173`.

### Health-check polling approach

Use `httpx.get(url, timeout=5.0)` in a `time.sleep(2)` polling loop. `httpx` is already installed (`httpx==0.28.1`). The total timeout (default 60 s) should be read from an env var `APP_CONTAINER_HEALTH_TIMEOUT` with `int(os.environ.get(..., "60"))`. On timeout, raise `ContainerStartError`.

```python
import time, httpx

deadline = time.monotonic() + timeout_secs
while time.monotonic() < deadline:
    try:
        r = httpx.get(url, timeout=5.0)
        if r.status_code == 200:
            return url
    except httpx.RequestError:
        pass
    time.sleep(2)
raise ContainerStartError(f"App did not become healthy within {timeout_secs}s")
```

No `asyncio` — `qa_pipeline.run()` calls this from within the async function but there is no `await` needed; synchronous HTTP polling is fine and matches the existing `run_command` pattern.

### Serve command detection

```python
import json, pathlib

_SERVE_PREFERENCE = ["preview", "start", "dev"]

def _detect_serve_command(workspace_path: str) -> str:
    pkg = pathlib.Path(workspace_path) / "package.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    scripts = data.get("scripts", {})
    for key in _SERVE_PREFERENCE:
        if key in scripts:
            return key
    raise ValueError(f"No serve script found in package.json (checked {_SERVE_PREFERENCE})")
```

Log the chosen command at `INFO` level so it is traceable (SERVE-01 success criterion).

### Error handling and teardown

Define a module-level exception:

```python
class ContainerStartError(RuntimeError):
    """Raised when the target app container fails to become healthy."""
```

Structure the public function with `container_id = None` before the try, and `docker rm -f` in finally:

```python
def serve_app(workspace_path: str, compose_network: str, ...) -> str:
    container_id = None
    try:
        serve_cmd = _detect_serve_command(workspace_path)
        container_id = _start_container(workspace_path, serve_cmd, compose_network, ...)
        host_port = _get_host_port(container_id, ...)
        url = f"http://localhost:{host_port}"
        _wait_until_healthy(url, ...)
        return url
    except:  # noqa: bare-except — re-raise after cleanup
        raise
    finally:
        if container_id:
            _remove_container(container_id)
```

Wait — this tears down immediately on return, which means the container is gone before the caller uses the URL. The function must **not** tear down on success. The teardown must happen in the **caller** (`qa_pipeline.py`), analogous to how `cloned.workspace_path` teardown happens in `qa_pipeline`'s own `finally`.

Correct design: `serve_app` returns `(url, container_id)` or a context manager. Given the existing patterns, a **context manager** is the cleanest approach and does not require changing teardown responsibility:

```python
from contextlib import contextmanager

@contextmanager
def managed_app_container(workspace_path: str, compose_network: str, ...) -> Iterator[str]:
    container_id = None
    try:
        ...
        container_id = _start_container(...)
        url = _wait_until_healthy(...)
        yield url
    finally:
        if container_id:
            _remove_container(container_id)
```

Caller in `qa_pipeline.py`:
```python
with managed_app_container(cloned.workspace_path, compose_network) as live_url:
    pw_py_file_changes = await run_claude_playwright_generator(..., base_url=live_url)
    ...
# container removed here — outside the with block, always
```

This satisfies SERVE-04 (cleanup on pass, fail, timeout, exception) while keeping teardown co-located with the container lifecycle.

---

## Codebase File Map

| File | Role in Phase 27 |
|------|-----------------|
| `backend/services/app_container.py` | **New file** — `ContainerStartError`, `managed_app_container()`, helpers |
| `backend/services/qa_pipeline.py` | **Caller** — adds `with managed_app_container(...) as live_url:` block; passes `live_url` to `run_claude_playwright_generator`; removes `PLAYWRIGHT_BASE_URL` env-var gate logic for the served-app path |
| `backend/tests/test_app_container.py` | **New test file** — subprocess mocked; tests SERVE-01 through SERVE-04 |
| `docker-compose.yml` | **Read-only reference** — network name, `/tmp` volume mount |
| `backend/requirements.txt` | **No change** — `httpx` already present |
| `backend/services/repo_clone.py` | **Read-only reference** — workspace path pattern (`/tmp/jarvis-*`) |

---

## Validation Architecture

### What to verify

- **SERVE-01**: `_detect_serve_command` returns `preview` when `scripts` has `preview`+`start`, `start` when only `start`, `dev` when only `dev`, raises `ValueError` when none present
- **SERVE-02**: `docker run -d -p 0:PORT --network <net> -v workspace:/app ...` is called with list-form args and `shell=False`
- **SERVE-03**: `_wait_until_healthy` loops until HTTP 200, raises `ContainerStartError` on timeout
- **SERVE-04**: `_remove_container` called in `finally` regardless of exit path — success, `ContainerStartError`, unexpected exception

### Test approach

Mock `subprocess.run` (same pattern as `test_repo_clone.py`). Mock `httpx.get` (same pattern as `test_confluence_client.py` / `test_pr_creator.py` which mock `httpx.post`). No real Docker daemon needed.

```python
from unittest.mock import MagicMock, patch, call
import pytest

def test_detect_serve_command_prefers_preview():
    pkg = '{"scripts": {"preview": "vite preview", "start": "node server.js"}}'
    with patch("pathlib.Path.read_text", return_value=pkg):
        from services.app_container import _detect_serve_command
        assert _detect_serve_command("/workspace") == "preview"

def test_managed_app_container_removes_on_exception():
    """ContainerStartError during health-check still calls docker rm -f."""
    ...
    # Assert subprocess.run called with ["docker", "rm", "-f", container_id]
```

Use `pytest` (already installed) and `unittest.mock` — no new test frameworks.

---

## Risks and Constraints

1. **Container port to expose is unknown without running the app**: The serve command determines the port (e.g., `vite preview` defaults to `4173`, `next start` to `3000`). Mitigation: try both common ports via a small configurable list; or expose `0:3000` and `0:4173` — for Phase 27, default to `3000` with an env var override `APP_CONTAINER_PORT`.

2. **Build step required for `preview`**: Vite/Next.js `preview` serves the production build; `npm run build` must run first. If the build fails, raise `ContainerStartError` with an informative message and skip E2E. Mitigation: attempt `npm ci && npm run build && npm run preview`; if `npm run build` exits non-zero, raise immediately.

3. **Docker socket DinD path**: The backend container accesses Docker via `/var/run/docker.sock` (mounted in `docker-compose.yml`). Containers started from the backend run on the **host** Docker daemon. Volume mounts in those containers must use paths visible on the host (hence the `/tmp:/tmp` mount in `docker-compose.yml`).

4. **Container cleanup race on SIGTERM**: If the backend process is killed mid-run, the `finally` block may not execute. Mitigation: use `--rm` flag on the container start command so Docker itself removes it when the container exits; combine with explicit `docker rm -f` in `finally` for the running container case. `--rm` alone is insufficient for running containers.

5. **Network name race**: `_resolve_compose_network()` does a subprocess call per invocation. If called from multiple concurrent QA runs, the result is idempotent (read-only), no race condition.

6. **`package.json` absent**: If the cloned repo has no `package.json`, `_detect_serve_command` raises `ValueError`. The caller in `qa_pipeline.py` must catch this and write a skip note (mirrors `e2e_skip_note` pattern already in place).

---

## RESEARCH COMPLETE
