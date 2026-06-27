"""SonarQube readiness polling and token bootstrap — SONAR-02, SONAR-03.

Owns all SonarQube lifecycle logic: wait for the service to reach UP status,
then create (or reuse) the scanner token that Phase 30 will pass to
sonar-scanner-cli. The boundary mirrors app_container.py: thin functions that
qa_pipeline.py calls, no DB or Jira side effects.

Public API:
  ensure_sonarqube_ready()   — called by qa_pipeline.run(); no-op if SONAR_URL unset
  wait_until_ready()         — polls /api/system/status until UP or timeout
  bootstrap_token()          — idempotent token generator for SONAR_TOKEN env var
  SonarQubeNotReadyError     — raised when SonarQube does not reach UP in time
"""

import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

_TOKEN_NAME = "jarvis-scanner"


class SonarQubeNotReadyError(RuntimeError):
    """SonarQube did not reach status=UP within the allowed timeout."""


def wait_until_ready(base_url: str, timeout_secs: int = 120) -> None:
    """Poll /api/system/status until status=UP or deadline.

    Mirrors _wait_until_healthy() in app_container.py: compute a deadline,
    loop with httpx.get, swallow connection errors, sleep between attempts.

    Args:
        base_url:     SonarQube base URL, e.g. "http://sonarqube:9000".
        timeout_secs: Default overridden by SONAR_READY_TIMEOUT env var.

    Raises:
        SonarQubeNotReadyError: If UP is not reached within the timeout.
    """
    # Allow operators and tests to shorten the deadline via env var.
    timeout_secs = int(os.environ.get("SONAR_READY_TIMEOUT", str(timeout_secs)))
    deadline = time.monotonic() + timeout_secs

    while time.monotonic() < deadline:
        try:
            r = httpx.get(f"{base_url}/api/system/status", timeout=5.0)
            if r.status_code == 200 and r.json().get("status") == "UP":
                logger.info("SonarQube is UP at %s", base_url)
                return
            logger.debug(
                "SonarQube not UP yet at %s: status=%s",
                base_url,
                r.json().get("status") if r.status_code == 200 else r.status_code,
            )
        except (httpx.RequestError, ValueError):
            # httpx.RequestError: connection refused / timeout
            # ValueError: bad JSON from r.json()
            logger.debug("SonarQube not reachable at %s (will retry)", base_url)

        time.sleep(5)

    raise SonarQubeNotReadyError(
        f"SonarQube did not reach UP within {timeout_secs}s at {base_url}"
    )


def bootstrap_token(base_url: str, admin_password: str | None = None) -> str:
    """Idempotent SonarQube scanner token generator.

    Returns SONAR_TOKEN from env immediately (idempotent across restarts).
    Otherwise revokes any existing 'jarvis-scanner' token in SonarQube (we
    cannot retrieve the original value via the API) and generates a fresh one,
    storing it in os.environ["SONAR_TOKEN"] so Phase 30 can read it without
    a DB round-trip.

    Args:
        base_url:       SonarQube base URL.
        admin_password: Admin password. Defaults to SONAR_ADMIN_PASSWORD env
                        var, then falls back to the SonarQube default "admin".

    Returns:
        The usable token string.
    """
    # Idempotent: if the operator already pinned the token, use it.
    if existing := os.environ.get("SONAR_TOKEN"):
        logger.info("SONAR_TOKEN already set in env — reusing")
        return existing

    password = admin_password or os.environ.get("SONAR_ADMIN_PASSWORD", "admin")
    auth = ("admin", password)

    # Search for an existing token by name.
    r = httpx.get(f"{base_url}/api/user_tokens/search", auth=auth, timeout=10.0)
    r.raise_for_status()
    token_names = [t["name"] for t in r.json().get("userTokens", [])]

    if _TOKEN_NAME in token_names:
        # Cannot retrieve value via API — must revoke and regenerate.
        logger.info("Revoking existing SonarQube token '%s'", _TOKEN_NAME)
        rev = httpx.post(
            f"{base_url}/api/user_tokens/revoke",
            auth=auth,
            data={"name": _TOKEN_NAME},
            timeout=10.0,
        )
        rev.raise_for_status()

    logger.info("Generating new SonarQube token '%s'", _TOKEN_NAME)
    gen = httpx.post(
        f"{base_url}/api/user_tokens/generate",
        auth=auth,
        data={"name": _TOKEN_NAME},
        timeout=10.0,
    )
    gen.raise_for_status()
    token = gen.json()["token"]

    os.environ["SONAR_TOKEN"] = token
    logger.info("SONAR_TOKEN bootstrapped and stored in env")
    return token


def ensure_sonarqube_ready(base_url: str | None = None) -> None:
    """Ensure SonarQube is reachable and scanner token is bootstrapped.

    Called by qa_pipeline.run() before the clone step. Reads SONAR_URL from
    env when base_url is not passed explicitly. If neither is set, returns
    immediately — SonarQube is not in the stack for this deployment.

    Raises:
        SonarQubeNotReadyError: propagated from wait_until_ready on timeout.
        httpx.HTTPStatusError:  propagated from bootstrap_token on API failure.
    """
    url = base_url or os.environ.get("SONAR_URL")
    if not url:
        # ponytail: SONAR_URL absent = SonarQube not in stack; skip silently
        return

    logger.info("Ensuring SonarQube is ready at %s", url)
    wait_until_ready(url)
    bootstrap_token(url)
