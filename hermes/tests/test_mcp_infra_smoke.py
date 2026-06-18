"""
Smoke tests for Phase 7 MCP Infrastructure (MCPINFRA-01, MCPINFRA-02, MCPINFRA-03).

All tests are offline — no Docker daemon or network calls required. They verify:
  - docker-compose.yml configuration on disk
  - Python package availability in the current environment

These tests are designed to run both locally and inside the hermes Docker container.
"""
import pathlib
import pytest

import yaml

pytestmark = pytest.mark.unit


def _load_compose() -> dict:
    """Walk up from this file until docker-compose.yml is found (handles
    running from hermes/ subdirectory or from the repo root)."""
    candidate = pathlib.Path(__file__).resolve()
    for _ in range(10):
        candidate = candidate.parent
        compose_file = candidate / "docker-compose.yml"
        if compose_file.exists():
            with compose_file.open() as f:
                return yaml.safe_load(f)
    raise FileNotFoundError(
        "docker-compose.yml not found walking up from " + str(pathlib.Path(__file__))
    )


@pytest.fixture(scope="module")
def compose() -> dict:
    return _load_compose()


def test_config_has_sse_transport(compose: dict) -> None:
    """mcp-atlassian service must declare TRANSPORT=sse for HTTP/SSE mode."""
    services = compose.get("services", {})
    assert "mcp-atlassian" in services, (
        "mcp-atlassian service is missing from docker-compose.yml (MCPINFRA-01)"
    )
    env = services["mcp-atlassian"].get("environment", [])
    # environment may be a list of "KEY=VALUE" strings or a dict
    if isinstance(env, dict):
        env_strs = [f"{k}={v}" for k, v in env.items()]
    else:
        env_strs = list(env)
    assert any(e.startswith("TRANSPORT=sse") for e in env_strs), (
        "TRANSPORT=sse must be set in mcp-atlassian environment to enable HTTP/SSE mode"
    )


def test_config_no_static_jira_creds(compose: dict) -> None:
    """Static Jira credential vars must NOT appear in mcp-atlassian env.

    Their absence is what activates per-request (multi-user) credential mode.
    Setting them would lock the server to a single Jira instance and expose
    credentials in `docker inspect` output (T-07-01, MCPINFRA-02).
    """
    services = compose.get("services", {})
    assert "mcp-atlassian" in services, (
        "mcp-atlassian service is missing from docker-compose.yml"
    )
    env = services["mcp-atlassian"].get("environment", [])
    if isinstance(env, dict):
        env_keys = set(env.keys())
        env_strs = [f"{k}={v}" for k, v in env.items()]
    else:
        env_strs = list(env)
        env_keys = {s.split("=")[0] for s in env_strs if "=" in s}

    forbidden = {"JIRA_URL", "JIRA_USERNAME", "JIRA_API_TOKEN"}
    found = forbidden & env_keys
    assert not found, (
        f"{found} must not appear in mcp-atlassian env — "
        "static creds would disable per-request mode (MCPINFRA-02)"
    )


def test_hermes_env_has_mcp_url(compose: dict) -> None:
    """Hermes service environment must include MCP_ATLASSIAN_URL."""
    services = compose.get("services", {})
    assert "hermes" in services, "hermes service missing from docker-compose.yml"
    env = services["hermes"].get("environment", [])
    if isinstance(env, dict):
        env_strs = [f"{k}={v}" for k, v in env.items()]
    else:
        env_strs = list(env)
    assert any(e.startswith("MCP_ATLASSIAN_URL=") for e in env_strs), (
        "MCP_ATLASSIAN_URL must appear in hermes environment so the container "
        "knows how to reach mcp-atlassian (MCPINFRA-01)"
    )


def test_mcp_sdk_importable() -> None:
    """The Python MCP SDK must be importable (MCPINFRA-03)."""
    try:
        import mcp  # noqa: F401
    except ImportError as exc:
        pytest.fail(
            f"import mcp failed — mcp>=1.0 must be installed in the hermes image: {exc}"
        )


def test_httpx_sse_importable() -> None:
    """httpx-sse must be importable for SSE transport (MCPINFRA-03)."""
    try:
        import httpx_sse  # noqa: F401
    except ImportError as exc:
        pytest.fail(
            f"import httpx_sse failed — httpx-sse>=0.4 must be installed in the hermes image: {exc}"
        )
