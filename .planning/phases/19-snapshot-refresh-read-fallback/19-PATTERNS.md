# Phase 19: Snapshot Refresh & Read Fallback - Pattern Map

**Mapped:** 2026-06-22
**Files analyzed:** 2 (1 modified, 1 new/modified — exact new-file count depends on planner's split)
**Analogs found:** 2 / 2

No CONTEXT.md or RESEARCH.md exist for this phase (yolo mode — research/discuss skipped). File list and scope derived directly from ROADMAP.md Phase 19 section, REQUIREMENTS.md (SNAPSHOT-01, SNAPSHOT-02), and the Phase 18 codebase scan service + Phase 17 merge pipeline implementations already in the repo.

## Requirements Recap

- **SNAPSHOT-01**: After a successful `@jarvis merge pr`, the agent re-clones/re-scans the repo and pushes an updated `.hermes/codebase.md` to main automatically.
- **SNAPSHOT-02**: When a pipeline stage reads `.hermes/codebase.md` and the file does not exist, the pipeline continues without codebase context — no exception, no empty-error surfaced to the user.

Note: there is currently **no existing reader** of `.hermes/codebase.md` anywhere in `backend/` or `hermes/` (confirmed via grep — only `codebase_scan_service.py` writes it). The read-fallback function built in this phase is a **new utility with no consumer yet** — Phase 20 (`describe_pipeline.py`) and Phase 21 (`architecture_pipeline.py`) will be its first callers. Build it as a standalone, reusable function now so those phases can import it directly.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/services/merge_pipeline.py` (modified — add post-merge re-scan hook) | service (orchestrator hook) | event-driven | `backend/routers/projects.py` lines 87-133 (`_run_scan_background` background-task pattern around `codebase_scan_service.run()`) | exact |
| `backend/services/codebase_snapshot_reader.py` (new — read-fallback helper, e.g. `get_codebase_snapshot()`) | service (utility) | request-response (degrades to no-op) | `backend/services/hermes_client.py` lines 279-311 (`get_comments`, graceful try/except returning `[]`) | exact |
| `backend/tests/test_merge_pipeline.py` (modified — add re-scan trigger assertions) | test | event-driven | existing tests in same file (no new analog needed — extend in place) | exact |
| `backend/tests/test_codebase_snapshot_reader.py` (new) | test | request-response | `backend/tests/test_codebase_scan_service.py` (respx-mocked GitHub API test structure) | role-match |

## Pattern Assignments

### `backend/services/merge_pipeline.py` (service hook, event-driven) — SNAPSHOT-01

**Analog:** `backend/routers/projects.py` lines 87-133 (`_run_scan_background`)

This is the only place in the codebase that already calls `codebase_scan_service.run()`. It demonstrates the exact shape the post-merge hook should take: open a fresh background-safe session reference (or, in this case, reuse the merge pipeline's already-open `bg_db` since `merge_pipeline.run()` is itself invoked from a background task — see `webhook.py` `_run_merge_background`), decrypt credentials, call `codebase_scan_service.run()`, and swallow/log failures without affecting the outer pipeline's success state.

**Reference pattern** (`backend/routers/projects.py:103-130`):
```python
async def _run_scan_background() -> None:
    # CR-02: Open a fresh session — never reuse the request-scoped db session.
    bg_db = SessionLocal()
    try:
        bg_project = bg_db.query(Project).filter(Project.id == project_id).first()
        if bg_project is None:
            logger.warning(
                "Project id=%s not found in scan background task — aborting",
                project_id,
            )
            return
        github_token = decrypt_credential(bg_project.github_token)  # T-18-01: not logged
        github_repo = decrypt_credential(bg_project.github_repo)
        try:
            await codebase_scan_service.run(github_repo, github_token, project_id, bg_db)
        except Exception as exc:
            logger.warning(
                "Codebase scan failed for project id=%s: %s", project_id, exc
            )
            bg_db.query(PipelineState).filter(
                PipelineState.project_id == project_id,
                PipelineState.stage == "codebase_scan",
                PipelineState.status == "running",
            ).update({"status": "error"})
            bg_db.commit()
    finally:
        bg_db.close()
```

**Insertion point in `merge_pipeline.run()`:** `backend/services/merge_pipeline.py` already decrypts `project.github_token`/`github_repo` implicitly via `pr_creator.find_and_merge_pr` (it receives `project` and decrypts internally — check `pr_creator.find_and_merge_pr` signature for exact decrypt call site). The re-scan call belongs **after** the `merge_result.merged` check succeeds (after line ~154, where `not merge_result.merged` raises) and **before** the final `state_row.status = "complete"` at line 194 — i.e., as Step 6.5, between Jira status transition (Step 5/6) and state-row finalisation (Step 7). Critically, per SNAPSHOT-01's framing ("snapshot stays current — developer takes no additional action") and the existing merge_pipeline graceful-degradation convention (T-17-07: "no open PR found" is not a pipeline failure), **the re-scan call must be wrapped in its own try/except so a scan failure never flips the merge pipeline's overall `state_row.status` to `"failed"`** — the PR was still successfully merged. Log a warning and continue to the confirmation comment.

**Imports to add** (mirror `backend/routers/projects.py:27`):
```python
from services import codebase_scan_service
```

**Decrypt call already present in scope** — `project.github_token` and `project.github_repo` are Project ORM fields; use the same `decrypt_credential()` already imported at `backend/services/merge_pipeline.py:35`:
```python
from services.crypto import decrypt_credential
...
github_token = decrypt_credential(project.github_token)  # T-17-05/T-18-01 convention: never logged
github_repo = decrypt_credential(project.github_repo)
```

**Error isolation pattern** (mirror the inner try/except in `_run_scan_background`, but do NOT mark any PipelineState as "error" — this is a best-effort side-action, not the primary pipeline stage):
```python
try:
    await codebase_scan_service.run(github_repo, github_token, project.id, db)
    logger.info("Codebase snapshot refreshed after merge for project id=%d", project.id)
except Exception as exc:
    logger.warning(
        "Post-merge codebase snapshot refresh failed for project id=%s: %s — merge still succeeded",
        project.id, exc,
    )
```

**Why `codebase_scan_service.run()` needs no changes:** it already has idempotent overwrite logic (Step 13 "Idempotency GET — fetch existing sha", `backend/services/codebase_scan_service.py:348-352`), so calling `run()` again after merge naturally produces an update-in-place PUT rather than a duplicate-file error. No "re-clone" step is needed in the literal git-clone sense — `codebase_scan_service.run()` already uses the GitHub Contents/Trees API exclusively (no local clone), so "re-clone" in the success criteria is effectively just "re-run the scan."

---

### `backend/services/codebase_snapshot_reader.py` (new utility, request-response) — SNAPSHOT-02

**Analog:** `backend/services/hermes_client.py` lines 279-311 (`get_comments`)

This is the strongest existing graceful-degradation precedent in the codebase: wrap the network call in try/except, return an empty/falsy sentinel on **any** error (network, timeout, non-2xx, bad JSON, 404), log a warning with no sensitive values, and never raise.

**Reference pattern** (`backend/services/hermes_client.py:279-311`):
```python
async def get_comments(
    jira_url: str,
    jira_email: str,
    jira_token: str,
    issue_key: str,
) -> list[dict]:
    """Fetch comment history for a Jira issue via hermes POST /jira/comments.

    Returns [] on any error — DEVPIPE-01 requires the pipeline to not crash
    if comment history is unavailable. The caller should post an informative
    Jira comment if no architecture URL is found after degradation.

    T-09-01: jira_token is never logged; only issue_key is logged at INFO.
    """
    try:
        logger.info("Fetching comments for issue %s", issue_key)
        payload = {...}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{HERMES_BASE_URL}/jira/comments", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning(
            "get_comments failed for issue %s: %s — returning []",
            issue_key,
            exc,
        )
        return []
```

**Apply this shape to the new reader, returning `None` (or `""`) instead of `[]`** since the codebase snapshot is a single markdown blob, not a list:

```python
async def get_codebase_snapshot(github_repo: str, github_token: str) -> str | None:
    """Fetch .hermes/codebase.md content via GitHub Contents API.

    Returns None if the file does not exist (404) or any other error occurs
    (network, timeout, non-2xx, bad JSON) — SNAPSHOT-02 requires callers to
    continue without codebase context rather than crash or surface an error.

    T-18-01 convention: github_token is never logged.
    """
    parsed = _parse_owner_repo(github_repo)  # reuse helper from codebase_scan_service
    if parsed is None:
        return None
    owner, repo = parsed
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api_base = os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)
    try:
        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            resp = await client.get(f"{api_base}/repos/{owner}/{repo}/contents/.hermes/codebase.md")
        if resp.status_code == 404:
            logger.info("No codebase snapshot found for %s/%s — continuing without context", owner, repo)
            return None
        resp.raise_for_status()
        content_b64 = resp.json().get("content", "")
        return base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning(
            "Codebase snapshot fetch failed for %s/%s: %s — continuing without context",
            owner, repo, exc,
        )
        return None
```

**Reuse, don't duplicate, the owner/repo parsing and GitHub API base/headers conventions** already established in `codebase_scan_service.py`:
- `_parse_owner_repo()` helper (private function in `codebase_scan_service.py` — either import it directly via `from services.codebase_scan_service import _parse_owner_repo` or, better, promote it to a shared module if the planner decides both files need it; do not re-implement parsing logic from scratch)
- `GITHUB_API_BASE` constant and `os.environ.get("GITHUB_API_BASE", GITHUB_API_BASE)` override pattern (`backend/services/codebase_scan_service.py:281`)
- `headers` dict shape with `Authorization: Bearer {token}` (`backend/services/codebase_scan_service.py:289-293`) — T-18-01 convention: token only ever placed in this header dict, never in an f-string, log call, or exception message

**Imports pattern** (mirror `backend/services/codebase_scan_service.py:1-20` for httpx/base64/logging/os conventions):
```python
import base64
import logging
import os

import httpx

logger = logging.getLogger(__name__)
```

---

## Shared Patterns

### Graceful Degradation (never raise, return sentinel, log + continue)
**Source:** `backend/services/hermes_client.py:224-271` (`update_status` → `bool`) and `:279-311` (`get_comments` → `list[dict]`)
**Apply to:** `codebase_snapshot_reader.get_codebase_snapshot()` (SNAPSHOT-02) and the post-merge re-scan try/except in `merge_pipeline.run()` (SNAPSHOT-01's failure path)
```python
try:
    ...
except Exception as exc:
    logger.warning("<fn> failed for <id>: %s — returning <sentinel>", exc)
    return <sentinel>
```

### Token/credential never logged or interpolated into exception strings
**Source:** `backend/services/codebase_scan_service.py:288-293` (T-18-01), `backend/services/pr_creator.py:74,102-104` (T-07-01 stderr scrubbing)
**Apply to:** Both new/modified files — `github_token` must only ever appear inside the `Authorization` header dict; all `logger.*` and `RuntimeError`/exception-message strings must interpolate only `owner`, `repo`, `status_code`, or `project_id` — never the token itself.

### Background-task session isolation (CR-02 convention)
**Source:** `backend/routers/projects.py:104-130`, `backend/routers/webhook.py:413-431`
**Apply to:** The post-merge re-scan hook in `merge_pipeline.py` — note `merge_pipeline.run()` already receives its `db` session from `webhook.py`'s `_run_merge_background()` (a fresh `SessionLocal()`, never request-scoped), so the re-scan call can reuse that same `db` session directly without opening another one — no new session-isolation work needed here, just confirm the existing convention is preserved (do not pass a request-scoped session).

### Idempotent overwrite via existing-SHA GET-before-PUT
**Source:** `backend/services/codebase_scan_service.py:348-361` (Step 13-14)
**Apply to:** No changes needed — `codebase_scan_service.run()` already handles "snapshot already exists" by fetching the existing blob SHA and including it in the PUT body. The post-merge re-scan hook can call `run()` exactly as-is; it does not need a separate "update" code path.

## No Analog Found

None — both required new/modified files have exact-match analogs already in the codebase (graceful-degradation read function and background-task scan-trigger hook are both established patterns from Phases 16-18).

## Metadata

**Analog search scope:** `backend/services/`, `backend/routers/`, `backend/tests/`, `hermes/`
**Files scanned:** `codebase_scan_service.py`, `merge_pipeline.py`, `pr_creator.py`, `repo_clone.py`, `hermes_client.py`, `webhook.py`, `projects.py`, `mcp_client.py` (grep only — no `.hermes/codebase.md` reader found)
**Pattern extraction date:** 2026-06-22
