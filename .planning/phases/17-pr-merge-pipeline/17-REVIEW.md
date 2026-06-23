---
phase: 17-pr-merge-pipeline
reviewed: 2026-06-21T00:00:00Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - backend/routers/webhook.py
  - backend/services/hermes_client.py
  - backend/services/merge_pipeline.py
  - backend/services/pr_creator.py
  - backend/tests/test_hermes_client.py
  - backend/tests/test_merge_pipeline.py
  - backend/tests/test_pr_creator.py
  - backend/tests/test_webhook.py
  - hermes/mcp_client.py
  - hermes/server.py
findings:
  critical: 4
  warning: 6
  info: 2
  total: 12
status: issues_found
---

# Phase 17: Code Review Report

**Reviewed:** 2026-06-21T00:00:00Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

This phase implemented the PR merge pipeline (`@jarvis merge pr`), including `merge_pipeline.py`, the `find_and_merge_pr` function in `pr_creator.py`, the `update_status` path in `hermes_client.py`, and the `/jira/status` endpoint in `hermes/server.py`. The implementation is generally well-structured with correct idempotency guards and session-boundary discipline. However, several security and correctness defects were found:

- Two critical security issues: (1) Confluence API tokens are transmitted as URL query parameters on GET endpoints, violating the "never in URL" invariant stated in T-04-05; (2) CQL injection is possible in `find_confluence_page` via an unescaped `title` parameter.
- Two critical correctness bugs: (1) all three background task closures (architecture, dev_pipeline, merge_pr) pass `bg_project` to pipeline functions without a None check, causing unhandled `AttributeError` if the project is deleted between webhook receipt and background execution; (2) `merge_pipeline.run()` posts a "PR merged" confirmation comment without checking `merge_result.merged == True`.
- Several warnings covering token exposure in error messages, non-timing-safe webhook secret comparison, and missing GitHub API pagination.

---

## Critical Issues

### CR-01: Confluence token transmitted in URL query parameters

**File:** `hermes/server.py:173-192` and `hermes/server.py:231-252`; `backend/services/hermes_client.py:196-204` and `hermes_client.py:323-331`

**Issue:** The `GET /confluence/search` and `GET /confluence/page/{page_id}` endpoints in `hermes/server.py` declare `confluence_token` (and `confluence_email`, `confluence_url`) as plain function parameters — in FastAPI, this means they are received as URL query string parameters. The `hermes_client.py` counterparts send these values in the `params=` dict to `httpx`, which encodes them into the URL query string. API tokens in query strings are recorded in server access logs, HTTP proxy logs, and browser history, directly violating the project's T-04-05 security requirement ("confluence_token is never logged").

The same design was avoided for POST endpoints (the `SprintBacklogRequest`, `GetCommentsRequest` etc. use request body models), making this an inconsistency.

**Fix:** Convert both GET endpoints to POST endpoints with Pydantic request body models, mirroring the `GetCommentsRequest` pattern used by `/jira/comments`. Update the corresponding `hermes_client.py` callers to use `client.post(...)` with `json=payload` instead of `client.get(..., params=params)`.

```python
# hermes/server.py — replace GET with POST
class SearchConfluencePageRequest(BaseModel):
    confluence_url: str
    confluence_email: str
    confluence_token: str
    space_key: str
    title: str

@app.post("/confluence/search")
async def post_confluence_search(
    req: SearchConfluencePageRequest,
    client: HermesMCPClient = Depends(get_mcp_client),
):
    creds = ConfluenceCredentials(
        confluence_url=req.confluence_url,
        confluence_email=req.confluence_email,
        confluence_token=req.confluence_token,
    )
    ...
```

---

### CR-02: CQL injection in `find_confluence_page` via unescaped title

**File:** `hermes/mcp_client.py:184`

**Issue:** The CQL query is constructed via f-string interpolation with the raw `title` parameter:

```python
"query": f'space = "{space_key}" AND title = "{title}"',
```

If `title` contains a double-quote character (e.g., `My "Feature" Page`), an attacker or an LLM-generated title with adversarial content can break out of the quoted string and inject arbitrary CQL. Example: a title of `x" OR space = "ADMIN` produces `space = "PROJ" AND title = "x" OR space = "ADMIN"`, which returns pages from the ADMIN space regardless of the intended space constraint. Since titles can be derived from LLM-generated architecture page names, this is a realistic injection surface.

**Fix:** Escape double-quote characters in both `space_key` and `title` before interpolation, or switch to a parameterized query format if the MCP tool supports it:

```python
safe_space = space_key.replace('"', '\\"')
safe_title = title.replace('"', '\\"')
"query": f'space = "{safe_space}" AND title = "{safe_title}"',
```

---

### CR-03: `bg_project` can be None — unguarded AttributeError in all three background tasks

**File:** `backend/routers/webhook.py:242-244`, `backend/routers/webhook.py:326-328`, `backend/routers/webhook.py:392-394`

**Issue:** All three background task closures (`_run_architecture_background`, `_run_dev_pipeline_background`, `_run_merge_background`) query the Project by `project_id` from a fresh DB session and then immediately pass the result to the pipeline without checking for None:

```python
bg_project = bg_db.query(Project).filter(Project.id == project_id).first()
await merge_pipeline.run(
    bg_project, event.issue.key, issue_summary, issue_description, bg_db
)
```

If the project is deleted between when the webhook handler commits the `PipelineState` row and when the background coroutine executes, `bg_project` is `None`. The pipeline functions immediately access `project.jira_url`, `project.github_token`, etc., causing an `AttributeError` that propagates as an unhandled exception in the background task — the `PipelineState` row is left stuck at `status="running"` with no failure comment posted to Jira.

**Fix:** Add a None guard in each background closure:

```python
async def _run_merge_background() -> None:
    bg_db = SessionLocal()
    try:
        bg_project = bg_db.query(Project).filter(Project.id == project_id).first()
        if bg_project is None:
            logger.error(
                "Project id=%s not found in background task for issue %s — aborting merge",
                project_id, event.issue.key,
            )
            return
        await merge_pipeline.run(
            bg_project, event.issue.key, issue_summary, issue_description, bg_db
        )
    finally:
        bg_db.close()
```

---

### CR-04: `merge_pipeline.run()` posts "PR merged" comment without checking `merge_result.merged`

**File:** `backend/services/merge_pipeline.py:119-186`

**Issue:** `find_and_merge_pr` returns a `MergeResult` dataclass with a `merged: bool` field. The `run()` function constructs and posts a comment stating "PR #N merged for {issue_key}" (line 171) without ever checking `merge_result.merged`. While GitHub's API returns HTTP 405 for unmergeable PRs (which would raise `RuntimeError`), a 200 response with `merged: false` is possible in edge cases (e.g., some GitHub Enterprise configurations or race conditions). The code would then post a false confirmation to Jira, claiming a successful merge when none occurred.

**Fix:** Add an explicit check immediately after `find_and_merge_pr`:

```python
merge_result = find_and_merge_pr(github_repo, github_token, issue_key)

if merge_result is None:
    # ... existing no-PR-found path ...

if not merge_result.merged:
    raise RuntimeError(
        f"GitHub reported PR #{merge_result.pr_number} was not merged "
        f"(merged=False in API response)"
    )

# Step 4: PR confirmed merged — proceed with Jira update ...
```

---

## Warnings

### WR-01: Non-timing-safe webhook secret comparison

**File:** `backend/routers/webhook.py:87`

**Issue:** The webhook secret is compared using `!=` (Python's native string equality):

```python
if x_jira_webhook_secret is None or x_jira_webhook_secret != expected_secret:
```

This comparison is vulnerable to timing attacks, where an attacker can infer characters of the secret by measuring response times across many requests. HMAC-based comparison (`hmac.compare_digest`) runs in constant time regardless of where the strings diverge.

**Fix:**
```python
import hmac

if x_jira_webhook_secret is None or not hmac.compare_digest(
    x_jira_webhook_secret, expected_secret
):
    raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")
```

---

### WR-02: Exception message from `find_and_merge_pr` interpolated into Jira failure comment

**File:** `backend/services/merge_pipeline.py:203-204`

**Issue:** The failure notification comment includes the raw exception message:

```python
failure_body = (
    f"Merge pipeline failed for {issue_key}: {exc}"
)
```

`exc` is the exception from `find_and_merge_pr` or `hermes_post_comment`. While `pr_creator.py`'s `RuntimeError` messages are token-safe (the token is only in HTTP headers, not exception strings), the generic `except Exception as exc` path in `pr_creator.py` lines 273-275 and 362 does include `{exc}` directly. The `httpx` exception for a failed generic request might include URL parameters or other sensitive data in its string representation under certain conditions. Additionally, any future exception type that does include a token or credential in its `str()` would immediately expose it in the Jira comment visible to all ticket viewers.

**Fix:** Replace `{exc}` in the failure body with a sanitized string:

```python
failure_body = (
    f"Merge pipeline failed for {issue_key}. "
    f"Check server logs for details."
)
```

Log the full exception via `logger.exception(...)` (already done at line 215) for debugging without exposing it to users.

---

### WR-03: `find_and_merge_pr` uses module-level `GITHUB_API_BASE` constant, not re-read from env

**File:** `backend/services/pr_creator.py:336`

**Issue:** `apply_commit_push_and_open_pr` re-reads `GITHUB_API_BASE` from the environment at call time (line 240: `api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)`), supporting test overrides via `os.environ`. However, `find_and_merge_pr` uses the module-level constant directly (line 336: `api_base = GITHUB_API_BASE`), which is evaluated at module import time. If `GITHUB_API_BASE` is set after module import (as in the `test_apply_commit_push_and_open_pr_success` test with `os.environ.setdefault`), the two functions use different base URLs. The `find_and_merge_pr` tests happen to work only because `respx` mocks `"https://api.github.com"` which matches the default, but overriding `GITHUB_API_BASE` in tests for `find_and_merge_pr` will silently fail.

**Fix:** Apply the same env-read pattern to `find_and_merge_pr`:

```python
# find_and_merge_pr, after parsing owner/repo
api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)
```

---

### WR-04: GitHub PR list API called without pagination — may miss the target PR

**File:** `backend/services/pr_creator.py:342-363`

**Issue:** `find_and_merge_pr` retrieves open PRs with `params={"state": "open"}` and no `per_page` or `page` parameter. GitHub's default page size is 30. If the repository has more than 30 open PRs at the time `@jarvis merge pr` is triggered, the jarvis-created PR may not appear in the first page and `find_and_merge_pr` returns `None` — causing `merge_pipeline.run()` to post an incorrect "No open PR found" comment despite an open PR existing. This is a correctness bug in repositories with high PR volume.

**Fix:** Add `per_page=100` (the GitHub API maximum) to the list request, or implement pagination:

```python
resp = httpx.get(
    f"{api_base}/repos/{owner}/{repo}/pulls",
    headers=headers,
    params={"state": "open", "per_page": 100},
    timeout=30.0,
)
```

For full correctness, also add a `head` filter: `params={"state": "open", "head": f"{owner}:{expected_branch}", "per_page": 1}` for the branch-based lookup.

---

### WR-05: `hermes/server.py` exception details serialized to HTTP response — potential internal info exposure

**File:** `hermes/server.py:56,66,76,87,155,169,190,226,251`

**Issue:** All nine endpoint handlers wrap MCP client calls with `except Exception as exc: raise HTTPException(status_code=500, detail=str(exc))`. The `str(exc)` of an MCP SDK exception or an `httpx` transport error may contain internal URLs (e.g., the MCP container address), stack details, or opaque protocol error strings. These are returned verbatim to the backend caller (`hermes_client.py`), which in some cases logs or re-raises them. While the hermes service is internal-only, this still leaks service topology and connection strings in error responses that propagate all the way back to `merge_pipeline.run()`'s failure notification comment (see WR-02).

**Fix:** Log the full exception at WARNING/ERROR level and return a safe generic message:

```python
except Exception as exc:
    logger.warning("MCP call failed: %s", exc)
    raise HTTPException(status_code=500, detail="Internal MCP error")
```

---

### WR-06: `mcp_client.py` — unguarded `result.content[0]` IndexError on empty MCP response

**File:** `hermes/mcp_client.py:73,101,122,170,191,232,266,334`

**Issue:** Every MCP tool call parses the response as `json.loads(result.content[0].text)` without checking that `result.content` is non-empty. If the MCP tool returns an empty `content` list (possible for certain error conditions, tool version mismatches, or when the tool returns no structured output), all eight call sites raise an `IndexError`. Most of these are not wrapped in exception handlers (only `transition_issue` and callers with graceful degradation absorb this). For pipeline-critical paths like `add_comment` and `update_description`, this crashes the full pipeline.

**Fix:** Add a guard at each call site, or create a shared helper:

```python
def _parse_mcp_result(result) -> Any:
    if not result.content:
        raise RuntimeError("MCP tool returned empty content list")
    return json.loads(result.content[0].text)
```

---

## Info

### IN-01: `JIRA_WEBHOOK_SECRET` not set silently permits all webhook traffic

**File:** `backend/routers/webhook.py:83-86`

**Issue:** The `verify_webhook_secret` dependency silently allows all requests when `JIRA_WEBHOOK_SECRET` is not set in the environment:

```python
expected_secret = os.environ.get("JIRA_WEBHOOK_SECRET")
if not expected_secret:
    return  # No secret configured — allow through
```

This is documented as intentional for dev/test environments. However, if the variable is accidentally unset in a production deployment (e.g., a misconfigured secret in the orchestration layer), the pipeline accepts all inbound traffic with no authentication. There is no startup warning or metric emitted.

**Fix:** Add a startup warning log and consider raising an error in production mode:

```python
if not expected_secret:
    logger.warning(
        "JIRA_WEBHOOK_SECRET is not set — webhook authentication is DISABLED. "
        "Set this variable in production to prevent unauthenticated pipeline triggers."
    )
    return
```

---

### IN-02: No tests for `merge_pr` retrigger from `failed` or `complete` states

**File:** `backend/tests/test_webhook.py`

**Issue:** The webhook tests for `merge_pr` cover: schedule (new), duplicate (running), and state-committed-before-task. They do not cover that `status="failed"` or `status="complete"` states allow a new `merge_pr` run (the idempotency guard only blocks `status="running"`). The equivalent tests exist for `architecture` (`test_architecture_failed_state_allows_new_run`) and `start_coding` (`test_start_coding_failed_state_allows_new_run`) but are absent for `merge_pr`. If the idempotency guard query were accidentally changed to include `"failed"` or `"complete"`, this would silently break retriggering.

**Fix:** Add `test_merge_pr_failed_state_allows_new_run` and `test_merge_pr_complete_state_allows_new_run` test cases following the same pattern as the existing architecture and start_coding variants.

---

_Reviewed: 2026-06-21T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
