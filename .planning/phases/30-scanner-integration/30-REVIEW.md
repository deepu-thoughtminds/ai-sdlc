---
phase: 30-scanner-integration
reviewed: 2026-06-27T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - backend/services/qa_pipeline.py
  - backend/services/sonar_scanner.py
  - backend/tests/test_sonar_scanner.py
  - docker-compose.yml
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 30: Code Review Report

**Reviewed:** 2026-06-27
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Phase 30 wires sonar-scanner-cli into the QA pipeline and moves `ensure_sonarqube_ready()` into `_run_sonar_step`'s try block so SonarQube unavailability produces a graceful `TestResult` instead of aborting the pipeline. The SCAN-04 path is structurally correct. The main concerns are: (1) the SONAR_TOKEN value is emitted verbatim into application logs via `run_command`'s existing `logger.info` call — a credential leak in any log aggregation system; (2) the total wall-clock time for a sonar step is up to 2× `SONAR_TIMEOUT_SECONDS` because the scanner run and the CE task poll each consume a full budget independently; (3) `httpx.HTTPStatusError` from `bootstrap_token` is not caught by the existing `except Exception` in `_run_sonar_step` — wait, it is, `Exception` is the base class. Let me re-examine what is actually uncaught.

The broad `except Exception` in `_run_sonar_step` (line 230) catches everything including `SonarQubeNotReadyError` and `httpx.HTTPStatusError`, so the SCAN-04 graceful-failure path works for all error types. Core correctness is sound.

---

## Critical Issues

### CR-01: SONAR_TOKEN emitted to application logs via run_command

**File:** `backend/services/sonar_scanner.py:63-70` / `backend/services/test_executor.py:224`

**Issue:** `run_sonar_scan` builds the Docker command with `"-e", f"SONAR_TOKEN={token}"` as list elements. `run_command` in `test_executor.py` unconditionally logs the full command list at INFO level:

```python
logger.info("Executing tool %s: %s", cmd.name, cmd.command)
```

This prints the entire command list including `SONAR_TOKEN=<secret>` to stdout/stderr and any log aggregator (Datadog, Splunk, CloudWatch, etc.). The token is a long-lived SonarQube API credential.

**Fix:** Pass the token via a Docker secret or a pre-set env file rather than an inline `-e` flag, OR redact sensitive `-e` entries before logging in `run_command`:

```python
# Option A — redact in run_command before logging (minimal diff)
def _redact_command(cmd_list: list[str]) -> list[str]:
    redacted = []
    skip_next = False
    for item in cmd_list:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
        elif item == "-e" and redacted and redacted[-1] != "-e":
            redacted.append(item)
            skip_next = True  # next item is VAR=VALUE, redact if it matches secrets
        else:
            redacted.append(item)
    return redacted
```

Or simpler: use Docker's `--env-file` with a temp file written with `600` permissions, then delete it after the run. This keeps the secret out of the process argument list entirely (visible in `/proc/<pid>/cmdline` on Linux until the container starts).

---

## Warnings

### WR-01: Double timeout budget — total Sonar step can block for 2× SONAR_TIMEOUT_SECONDS

**File:** `backend/services/sonar_scanner.py:79,94`

**Issue:** `timeout_secs` is applied once to `run_command(cmd, timeout=timeout_secs)` and again to `_poll_ce_task(..., timeout_secs)`. With the default of 300 s, the pipeline can block for up to 600 s (10 min) on a slow or hung SonarQube. The env var `SONAR_TIMEOUT_SECONDS` is named as if it is the total budget, which is misleading.

**Fix:** Either halve the budget for each phase or start a monotonic clock before the scan and subtract elapsed time from the CE poll budget:

```python
start = time.monotonic()
result = run_command(cmd, timeout=timeout_secs)
elapsed = int(time.monotonic() - start)
remaining = max(timeout_secs - elapsed, 1)
ce_status = _poll_ce_task(sonar_url, task_id, token, remaining)
```

---

### WR-02: backend depends_on sonarqube without service_healthy — backend starts before SonarQube is ready

**File:** `docker-compose.yml:111-114`

**Issue:** The `depends_on: sonarqube` entry is a plain list, not using `condition: service_healthy`. Docker Compose starts the backend container as soon as the SonarQube container process starts (not when its healthcheck passes). SonarQube takes 60–90 s to initialise its Elasticsearch node. During that window, any QA pipeline triggered immediately after startup will call `wait_until_ready()` with up to 120 s — which should recover, but adds latency and log noise. More critically, if `ensure_sonarqube_ready()` is somehow called from a path that does not go through `_run_sonar_step`'s try block, startup failures surface as unhandled errors.

**Fix:**

```yaml
depends_on:
  hermes:
    condition: service_started
  litellm:
    condition: service_started
  sonarqube:
    condition: service_healthy
```

This requires Compose v2 (already assumed by this file) and makes the healthcheck actually gate container startup.

---

### WR-03: test_poll_returns_timeout is non-deterministic about loop entry

**File:** `backend/tests/test_sonar_scanner.py:143-148`

**Issue:** The test passes `timeout_secs=0` and relies on the loop exiting immediately because `time.monotonic() + 0` is "already past". But `time.monotonic()` is not patched, so whether the while-loop body executes once before exiting depends on real-time elapsed between the `deadline = time.monotonic() + 0` assignment and the first `while time.monotonic() < deadline` check. On a loaded CI machine this is non-deterministic. The comment says "deadline already past" but that is only true if any CPU time passes between those two lines.

In practice the test is reliable because even if the loop body runs once, `httpx.get` raises `RequestError` (patched), `time.sleep` is mocked (instant), and then the deadline is genuinely past on the second check. The test will always return `TIMEOUT`. However, the comment is misleading and the design is fragile — a future change to the loop structure (e.g., a `do … while` equivalent) could break the assumption.

**Fix:** Patch `time.monotonic` to guarantee deterministic behavior, or use a small positive timeout (e.g., 1) and patch `time.monotonic` to advance it:

```python
def test_poll_returns_timeout(self):
    with patch("services.sonar_scanner.time.monotonic", side_effect=[0.0, 999.0]):
        with patch("httpx.get", side_effect=httpx.RequestError("down")):
            status = _poll_ce_task("http://sonar:9000", "tid", "tok", 30)
    assert status == "TIMEOUT"
```

---

## Info

### IN-01: No test for CE task FAILED/CANCELLED status

**File:** `backend/tests/test_sonar_scanner.py`

**Issue:** `run_sonar_scan` has three terminal CE statuses: `SUCCESS`, `TIMEOUT`, and a fallback for `FAILED`/`CANCELLED`. The fallback branch (line 113–118 of `sonar_scanner.py`) has no test. If a SonarQube analysis genuinely fails server-side, this path is unverified.

**Fix:** Add one test:

```python
def test_ce_task_failed(tmp_path):
    sw = tmp_path / ".scannerwork"
    sw.mkdir()
    (sw / "report-task.txt").write_text("ceTaskId=abc123\n", encoding="utf-8")
    ok_result = TestResult(tool="sonar-scanner", returncode=0, stdout="", stderr="", timed_out=False)
    with patch("services.sonar_scanner.run_command", return_value=ok_result):
        with patch("services.sonar_scanner._poll_ce_task", return_value="FAILED"):
            result = run_sonar_scan(str(tmp_path), "org__repo", "http://sonar:9000", "tok", "net")
    assert result.returncode == 1
    assert result.timed_out is False
    assert "FAILED" in result.stderr
```

---

### IN-02: SONAR_ADMIN_PASSWORD not documented in docker-compose environment block

**File:** `docker-compose.yml:104-110`

**Issue:** `bootstrap_token()` in `sonar_client.py` requires `SONAR_ADMIN_PASSWORD` when `SONAR_TOKEN` is not pre-set. The backend picks this up from `env_file: .env`, but the `environment:` block in docker-compose.yml does not list it alongside `SONAR_URL` and `SONAR_TIMEOUT_SECONDS`. A new operator will not know to set it, and the failure mode is a `RuntimeError` inside `_run_sonar_step`'s broad except block that produces a non-zero `TestResult` with an opaque "Sonar scan error: SONAR_ADMIN_PASSWORD env var must be set" message.

**Fix:** Add a commented-out entry to the backend `environment:` block as documentation:

```yaml
environment:
  - SONAR_URL=${SONAR_URL:-http://sonarqube:9000}
  - SONAR_TIMEOUT_SECONDS=${SONAR_TIMEOUT_SECONDS:-300}
  # Required when SONAR_TOKEN is not pre-set; set in .env
  # - SONAR_ADMIN_PASSWORD=${SONAR_ADMIN_PASSWORD}
```

---

_Reviewed: 2026-06-27_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
