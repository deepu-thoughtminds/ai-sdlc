---
phase: 23-qa-foundation-sandbox-execution
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - qa-sandbox/Dockerfile
  - docker-compose.yml
  - backend/models/pipeline_state.py
  - backend/services/test_executor.py
  - backend/services/qa_pipeline.py
  - backend/tests/test_pipeline_state.py
  - backend/tests/test_test_executor.py
  - backend/tests/test_qa_pipeline.py
findings:
  critical: 2
  warning: 4
  info: 2
  total: 8
status: fixed
---

# Phase 23: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 23 delivers the QA sandbox infrastructure (Docker image, compose wiring, PipelineState.qa_attempt column) and the execution skeleton (test_executor.py + qa_pipeline.py). The subprocess safety posture (list-form args, no shell=True) is sound. The threat mitigations T-23-01 through T-23-04 are implemented correctly in test_executor.py.

Two issues require fixes before this code ships: qa_pipeline.py's except block omits the protective try/except + rollback around the failure-path db.commit() that exists in every peer pipeline (merge_pipeline.py, dev_pipeline.py), and the failure-comment formatter interpolates the raw exception message into the Jira comment body — a security regression that merge_pipeline.py explicitly fixed (WR-02). Four additional warnings cover hardcoded timeout text, unpinned Dockerfile dependencies, an unauthenticated script-pipe install, and a missing structural test gate.

---

## Critical Issues

### CR-01: Missing rollback guard around failure-path `db.commit()` in `qa_pipeline.py`

**File:** `backend/services/qa_pipeline.py:141-142`

**Issue:** The `except Exception` block sets `state_row.status = "failed"` and then calls `db.commit()` bare — with no surrounding `try/except` and no `db.rollback()` fallback. If `db.commit()` itself fails (e.g. SQLite lock, constraint violation, connection reset), the exception propagates out of the except block, bypasses the Step 6 Jira comment post, and the ticket receives no failure notification. The caller (background task runner) sees an unhandled exception.

This is a direct deviation from the stated design principle "mirrors merge_pipeline.py structure exactly." `merge_pipeline.py` lines 221-225 wraps this commit in `try/except: db.rollback()` precisely to prevent this failure mode.

**Fix:**
```python
except Exception as exc:
    state_row.status = "failed"
    try:
        db.commit()
    except Exception:
        db.rollback()
    logger.exception("QA pipeline failed for ticket %s: %s", issue_key, exc)
    comment_text = (
        f"QA pipeline failed for {issue_key}.\n\n"
        "Check server logs for details."
    )
```

---

### CR-02: Raw exception message interpolated into Jira comment body — internal details exposed

**File:** `backend/services/qa_pipeline.py:144-147`

**Issue:** The failure comment is built as:
```python
comment_text = (
    f"QA pipeline failed for {issue_key}.\n\n"
    f"Error: {type(exc).__name__} — {exc}"
)
```

The raw `str(exc)` is posted publicly to the Jira ticket. Exception messages from clone_repository include the GitHub repo path (`"git clone failed for owner/repo with exit code 1"`); exceptions from httpx or the Jira client can include full request URLs, response bodies, or credential-adjacent transport details. merge_pipeline.py carries an explicit `WR-02` comment explaining why it does NOT include `{exc}` in the Jira comment body: "The raw exception string may contain internal URLs, stack details, or credential-adjacent data from httpx transport errors." qa_pipeline.py regresses this fix.

**Fix:** Log the full exception server-side (already done via `logger.exception`), post only a generic message to Jira:
```python
comment_text = (
    f"QA pipeline failed for {issue_key}. "
    "Check server logs for details."
)
```

---

## Warnings

### WR-01: `_format_static_analysis_comment` hardcodes `"120s"` regardless of actual timeout

**File:** `backend/services/qa_pipeline.py:200`

**Issue:** The comment formatter outputs `"TIMED OUT (120s)"` as a string literal. `run_static_analysis()` accepts a `timeout` parameter (default 120), but if a caller passes a custom timeout (e.g. Phase 25 may reduce it for the fix-loop), the comment will silently show the wrong value. The `TestResult.stderr` field already contains the actual timeout string set by `run_command()` (e.g. `"Command timed out after 60s"`), so the information is available without coupling to a magic number.

**Fix:**
```python
elif r.timed_out:
    # r.stderr already contains "Command timed out after Xs" from run_command()
    lines.append(f"- {r.tool}: TIMED OUT ({r.stderr})")
```
Or parameterize the timeout at the function signature level:
```python
def _format_static_analysis_comment(results, issue_key, timeout=120):
    ...
    lines.append(f"- {r.tool}: TIMED OUT ({timeout}s)")
```

---

### WR-02: Dockerfile installs tools without version pins — non-reproducible image

**File:** `qa-sandbox/Dockerfile:29-37`

**Issue:** Both `pip install` and `npm install -g` use unpinned versions:
```dockerfile
RUN pip install --no-cache-dir \
    ruff \
    mypy \
    bandit

RUN npm install -g \
    eslint \
    typescript
```
Rebuilding the image at a later date will silently install whatever versions are current at that moment. Static analysis tools change their rule sets and CLI flags between versions; an uncontrolled upgrade can turn previously-passing code into a failing QA run, or (less likely) relax rules that were previously catching issues. This is a reproducibility defect that will surface in CI when the image is rebuilt.

**Fix:** Pin to known-working versions:
```dockerfile
RUN pip install --no-cache-dir \
    "ruff==0.4.7" \
    "mypy==1.10.0" \
    "bandit==1.7.9"

RUN npm install -g \
    "eslint@8.57.0" \
    "typescript@5.4.5"
```

---

### WR-03: Dockerfile fetches and executes a remote shell script without integrity verification

**File:** `qa-sandbox/Dockerfile:23`

**Issue:**
```dockerfile
&& curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
```
This pattern downloads and immediately executes a shell script from an external URL. If the nodesource CDN is compromised, or if a DNS hijack routes the request to an attacker-controlled server, arbitrary code executes with root privileges inside the build container. curl's `-f` flag only fails on HTTP 4xx/5xx status codes; it does not verify the script's integrity via checksum or GPG signature.

While this is a well-known Docker anti-pattern that many projects accept pragmatically, the qa-sandbox image runs arbitrary third-party code (ruff, mypy, bandit, eslint) against developer repositories. A compromised build-time dependency has a direct path to reading checked-in secrets.

**Fix (preferred):** Use the official NodeSource APT repository with GPG key pinning, or switch to a multi-stage build using a maintained Node.js Docker base image:
```dockerfile
FROM node:20-slim AS node-base
FROM python:3.12-slim
COPY --from=node-base /usr/local/bin/node /usr/local/bin/node
COPY --from=node-base /usr/local/bin/npm /usr/local/bin/npm
# ... (copy lib paths as needed)
```

**Fix (minimal):** At minimum, verify the script checksum:
```dockerfile
RUN curl -fsSL https://deb.nodesource.com/setup_20.x -o /tmp/nodesource_setup.sh \
    && echo "EXPECTED_SHA256  /tmp/nodesource_setup.sh" | sha256sum -c - \
    && bash /tmp/nodesource_setup.sh
```

---

### WR-04: `QA_SANDBOX_IMAGE` read at module-import time — env var changes not picked up

**File:** `backend/services/test_executor.py:27`

**Issue:**
```python
QA_SANDBOX_IMAGE: str = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
```
This reads the env var once at import time. If a test or integration harness sets `os.environ["QA_SANDBOX_IMAGE"]` after the module is already imported (a common pattern in pytest fixtures), `detect_toolchain()` will silently use the stale value from import time. This also means that if the env var is changed at runtime (e.g. dynamic override in Phase 24's test generation stage), the change has no effect.

The `services/crypto.py` module explicitly documents this exact design decision in reverse: "The key is read lazily inside each function call (not cached at module level) so that test fixtures can set os.environ before calling." `test_executor.py` should follow the same pattern.

**Fix:**
```python
# Remove module-level constant; read per-call in detect_toolchain():
def detect_toolchain(workspace_path: str) -> list[ToolchainCommand]:
    image = os.environ.get("QA_SANDBOX_IMAGE", "qa-sandbox")
    ...
```

---

## Info

### IN-01: `test_test_executor.py` missing structural `shell=True` gate for `test_executor.py`

**File:** `backend/tests/test_test_executor.py` (missing test)

**Issue:** The plan spec (23-02-PLAN.md) calls for `test_no_shell_true_in_subprocess_calls` in `test_test_executor.py` (plan item 13): "inspect all subprocess.run mock calls; assert `shell` kwarg is never True (or never passed)." This test is absent from the file. The analogous structural gate exists only in `test_qa_pipeline.py` for `qa_pipeline.py`. The test count in the summary (17) does not match the actual count (16 functions in the file).

The T-23-01 acceptance criterion `grep -n 'shell=True' backend/services/test_executor.py returns no matches` is met by the source file, but the test suite does not verify this contractually. A future refactor could accidentally introduce `shell=True` in `test_executor.py` without a failing test.

**Fix:** Add a structural test to `test_test_executor.py`:
```python
def test_no_shell_true_in_subprocess_calls():
    """T-23-01 gate: shell=True never appears in live code in test_executor.py."""
    path = os.path.join(os.path.dirname(__file__), "..", "services", "test_executor.py")
    with open(path) as f:
        lines = f.readlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        assert "shell=True" not in line, f"shell=True found in live code: {line!r}"
```

---

### IN-02: `tsc` command omits `--project` flag specified in plan — relies on CWD resolution

**File:** `backend/services/test_executor.py:157-160`

**Issue:** The plan spec (23-02-PLAN.md line 89) specifies the tsc command as:
```
["docker", "run", "--rm", "-v", ..., image, "tsc", "--noEmit", "--project", "/workspace/tsconfig.json"]
```
The implementation uses:
```python
"tsc", "--noEmit",
```
(no `--project` flag). The `-w /workspace` Docker flag is set, so tsc will find `tsconfig.json` via the working directory. This works in the happy path, but is fragile: if `tsconfig.json` is in a subdirectory (e.g. `apps/web/tsconfig.json`), tsc will silently succeed with no files type-checked rather than failing or warning. The explicit `--project /workspace/tsconfig.json` path makes the failure mode explicit.

**Fix:**
```python
"tsc", "--noEmit", "--project", "/workspace/tsconfig.json",
```

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
