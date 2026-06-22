---
phase: 20-describe-pipeline-context
reviewed: 2026-06-22T00:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - backend/services/describe_pipeline.py
  - backend/tests/test_describe_pipeline.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 20: Code Review Report

**Reviewed:** 2026-06-22
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Phase 20 replaced `graphify_service.get_codebase_snapshot()` with `codebase_snapshot_reader.get_codebase_snapshot()` in the describe pipeline. The core refactor is structurally sound: no stale graphify imports remain in source (only in a doc-comment on line 10), credentials are not logged, and the snapshot truncation is in place.

However, one critical bug exists: `route_request` is a synchronous function but is called inside an `async def` without `await` — this is correct as written, but the function is NOT awaited and the return value is used synchronously, which is fine. The critical issue is the silent empty-string fallback when `github_repo` decryption fails: an empty string is passed to `get_codebase_snapshot`, which silently no-ops rather than surfacing the real problem. Three warnings cover: `route_request` is not awaited (correct — it is sync — but the lack of `await` in an async context warrants attention for future maintainers); missing test for decrypt failure paths; and the prompt including unvalidated `trigger_comment` from the Jira webhook body without explicit length guard at this layer.

---

## Critical Issues

### CR-01: Silent empty-string passed to `get_codebase_snapshot` when `github_repo` decrypt fails — causes invisible data loss

**File:** `backend/services/describe_pipeline.py:63-68`

**Issue:** When `decrypt_credential(project.github_repo)` raises (wrong key, corrupted ciphertext, `ENCRYPTION_KEY` not set), the `except Exception` silently sets `github_repo = ""`. The empty string is then passed to `get_codebase_snapshot("", ...)`. Inside `codebase_snapshot_reader._parse_owner_repo("")` this returns `None`, causing the snapshot to silently degrade to `"(no codebase context available)"` — indistinguishable from the normal "file not yet committed" case. No log entry is emitted at this layer to indicate the decrypt failure happened.

The same silent swallow exists for `github_token` (lines 57-60), compounding the problem: both the repo slug and the token can silently become empty without any observable signal, meaning a misconfigured or rotated encryption key produces no error, no warning, and a subtly degraded but non-failing pipeline run. This is a data-correctness failure.

**Fix:** Log a warning before swallowing the exception so the failure is observable, and treat an empty `github_repo` as a skip-with-log rather than a transparent passthrough:

```python
try:
    github_token = decrypt_credential(project.github_token) if project.github_token else ""
except Exception as exc:
    logger.warning(
        "Failed to decrypt github_token for issue %s — snapshot skipped: %s",
        getattr(getattr(event, "issue", None), "key", "UNKNOWN"),
        exc,
    )
    github_token = ""

try:
    github_repo = decrypt_credential(project.github_repo)
except Exception as exc:
    logger.warning(
        "Failed to decrypt github_repo for issue %s — snapshot skipped: %s",
        getattr(getattr(event, "issue", None), "key", "UNKNOWN"),
        exc,
    )
    github_repo = ""
```

Note: `issue_key` is computed later (line 91). Use `getattr` guards here, or restructure to extract `issue_key` before the decrypt block so it can be used in these log messages.

---

## Warnings

### WR-01: `route_request` is synchronous but called inside `async def run()` — no `await`, which is correct, but blocks the event loop

**File:** `backend/services/describe_pipeline.py:114`

**Issue:** `route_request` is defined as `def route_request(stage, prompt) -> LLMResponse` (synchronous). Calling it directly inside an `async def` without `await` is technically correct Python — it just runs synchronously. However, `route_request` makes a blocking HTTP call via `httpx` (not `httpx.AsyncClient`) based on its implementation. This blocks the asyncio event loop for the duration of the freellmapi round-trip. In a single-request test environment this is invisible, but in production under concurrent Jira webhooks this stalls all other coroutines.

**Fix:** Either wrap the call in `asyncio.get_event_loop().run_in_executor(None, route_request, "describe", prompt)`, or refactor `llm_router.route_request` to be `async` using `httpx.AsyncClient` (consistent with how `get_codebase_snapshot` is implemented). The async approach is preferred.

---

### WR-02: No test covers the decrypt-failure path — the most likely production error case is untested

**File:** `backend/tests/test_describe_pipeline.py`

**Issue:** There are four tests covering: happy path, empty backlog, no snapshot, and snapshot-in-prompt. None tests what happens when `decrypt_credential` raises (e.g., wrong `ENCRYPTION_KEY`, corrupted DB value). Given CR-01 above — where the failure is silently swallowed — there is no test that would catch a regression if the silence were removed or if the fallback behavior changed. The decrypt path is the most likely failure mode in a real deployment (key rotation, environment misconfiguration).

**Fix:** Add a test that patches `services.describe_pipeline.decrypt_credential` to raise `cryptography.fernet.InvalidToken` and asserts that `run()` still completes (graceful degradation) and that `route_request` is still called:

```python
def test_run_with_decrypt_failure():
    from cryptography.fernet import InvalidToken
    with (
        patch("services.describe_pipeline.decrypt_credential", side_effect=InvalidToken),
        patch("services.describe_pipeline.get_codebase_snapshot", new_callable=AsyncMock, return_value=None),
        patch("services.describe_pipeline.post_sprint_backlog", new_callable=AsyncMock, return_value=[]),
        patch("services.describe_pipeline.route_request",
              return_value=_make_stub_llm_response("ok")) as mock_route,
    ):
        result = asyncio.run(run(_make_mock_event(), _make_mock_project()))
        mock_route.assert_called_once()
        assert isinstance(result, str)
```

---

### WR-03: `trigger_comment` injected into prompt without length guard at this layer — relies entirely on upstream webhook validation

**File:** `backend/services/describe_pipeline.py:96,103`

**Issue:** `trigger_comment = getattr(event.comment, "body", "") or ""` is placed verbatim into the prompt (line 103) with no truncation. The docstring mentions "validated at webhook layer, max 10000 chars" but this is an assertion about an upstream contract, not an enforcement. If `describe_pipeline.run()` is ever called from a path that bypasses the webhook validator (e.g., a future internal trigger, a test, a replay mechanism), an unbounded comment body enters the prompt and the snapshot truncation at 8000 chars on line 88 is undermined.

The snapshot is truncated to 8000 chars (T-20-02) but the `trigger_comment` which also enters the prompt has no corresponding guard. A 10000-char comment plus an 8000-char snapshot plus fixed prompt text exceeds 20000 chars before the LLM context limit is considered.

**Fix:** Add a defensive truncation at this layer:

```python
MAX_COMMENT_CHARS = 4000
trigger_comment = (getattr(event.comment, "body", "") or "")[:MAX_COMMENT_CHARS]
```

---

## Info

### IN-01: Stale reference to "graphify" in module docstring

**File:** `backend/services/describe_pipeline.py:10`

**Issue:** Line 10 reads `"Replaces graphify_service with codebase_snapshot_reader for codebase context (Phase 20)."` This is transition prose that describes what changed in Phase 20 but will become misleading noise for future readers who never knew graphify was here. The module docstring should describe the current state, not the history.

**Fix:** Remove the transition sentence or replace with: `"Uses codebase_snapshot_reader for codebase context."` Migration history belongs in git commit messages.

---

### IN-02: `import asyncio` duplicated inside test functions

**File:** `backend/tests/test_describe_pipeline.py:95,128,160,196`

**Issue:** `import asyncio` appears at the top of the test module (line 12) and is re-imported inside four individual test function bodies (lines 95, 128, 160, 196). The inner imports are dead weight — Python caches the module so there is no semantic difference, but the repetition is misleading (implies the top-level import might not be sufficient) and creates unnecessary noise.

**Fix:** Remove the four `import asyncio` statements inside the test functions. The top-level import on line 12 is sufficient.

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
