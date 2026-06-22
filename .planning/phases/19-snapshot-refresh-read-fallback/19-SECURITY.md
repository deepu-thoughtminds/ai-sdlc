---
phase: 19-snapshot-refresh-read-fallback
threats_total: 6
threats_closed: 6
threats_open: 0
asvs_level: 1
audited: 2026-06-22
---

# Security Audit — Phase 19: Snapshot Refresh + Read Fallback

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-19-01 | Information Disclosure | mitigate | CLOSED | `merge_pipeline.py:207-213` — `scan_exc` interpolated only into `logger.warning`; grep confirms `scan_exc` never reaches `comment_text` or any `hermes_post_comment` argument. SHA confirmation comment built at line 181-185 (before the re-scan block at lines 201-213). |
| T-19-02 | Tampering | accept | CLOSED | `merge_pipeline.py:216` — `state_row.status = "complete"` is outside and after the re-scan try/except (lines 201-213). The only other `state_row.status` assignments are line 139 (no-PR branch) and line 221 (`"failed"` in outer except). The inner re-scan except block has no `state_row` assignment. No `db.commit()` inside re-scan try/except; Step 7 commit is at line 218. |
| T-19-03 | Denial of Service | mitigate | CLOSED | `merge_pipeline.py:201-213` — `await codebase_scan_service.run(...)` is wrapped in `try/except Exception as scan_exc`. Any exception (including hung GitHub API, RuntimeError from scan service) is caught, logged at WARNING, and does not re-raise. `state_row.status = "complete"` at line 216 executes unconditionally after the inner except. |
| T-19-04 | Information Disclosure | mitigate | CLOSED | `codebase_snapshot_reader.py:29,52,80` — `github_token` appears as: (1) function parameter name, (2) inside `Authorization` header dict value only. All `logger.info` (line 64) and `logger.warning` (line 80) calls interpolate only `owner`, `repo`, `exc` — never `github_token`. Enforced by `test_get_codebase_snapshot_token_never_in_logs_or_exceptions` (test_codebase_snapshot_reader.py:125-141). |
| T-19-05 | Denial of Service | mitigate | CLOSED | `codebase_snapshot_reader.py:58` — `httpx.AsyncClient(headers=headers, timeout=15.0)`. Blanket `except Exception as exc` at line 78 catches all timeout/connection errors and returns `None`. No exception propagates to caller. |
| T-19-06 | Repudiation | mitigate | CLOSED | `codebase_snapshot_reader.py:63-69` — `resp.status_code == 404` branch calls `logger.info(...)` (line 64, INFO level, not WARNING) and returns `None`. Same `None` sentinel as all other failure modes — uniform fallback path for callers. |

## Post-Review Fixes Verification

| Fix | Constraint Ref | Evidence |
|-----|---------------|----------|
| WR-02: empty content guard | `codebase_snapshot_reader.py:73-75` — `content_b64 = resp.json().get("content")` + `if not content_b64: return None` present. |
| WR-01: `%d` format in merge warning log | `merge_pipeline.py:209` — `"Post-merge codebase snapshot refresh failed for project id=%d: %s"` uses `%d` for `project.id`. |

## Unregistered Threat Flags

None. Both SUMMARY.md files (`19-01-SUMMARY.md` and `19-02-SUMMARY.md`) explicitly state no new threat surface beyond the registered threat model.

## Accepted Risks Log

T-19-02 is declared `accept` in the threat register. The accepted risk is: re-scan failure silently leaving the DB in a state where `.hermes/codebase.md` is stale relative to the just-merged commit. This is explicitly accepted because the scan is a best-effort background refresh; the merge itself is authoritative and its state (`"complete"`) is correct regardless.

## Summary

All 6 threats closed. No open threats. No unregistered flags. Phase 19 is clear to ship.
