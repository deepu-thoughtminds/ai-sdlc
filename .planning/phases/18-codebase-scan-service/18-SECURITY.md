---
phase: 18
slug: codebase-scan-service
status: verified
threats_open: 0
threats_total: 12
threats_closed: 12
asvs_level: 1
created: 2026-06-22
---

# Phase 18 — Codebase Scan Service — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Audited across plans 18-01 (service implementation), 18-02 (trigger wiring + tests),
> 18-03 (test-only gap closure), 18-04 (error-propagation gap closure).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|----------------|
| codebase_scan_service → GitHub API | github_token in Authorization header; response paths/content treated as data | Bearer token (outbound only), repo tree paths, file content (inbound) |
| GitHub API response → markdown output | Tree paths from GitHub treated as display strings (no eval/exec); content truncated at 2000 chars | Repo file paths and content snippets |
| markdown → GitHub Contents API PUT | Content base64-encoded; no credential values embedded | Base64-encoded markdown snapshot |
| create_project HTTP handler → asyncio.create_task | Decrypted github_token passed only to codebase_scan_service.run(); never logged | Decrypted GitHub token (in-process only) |
| _run_scan_background → SessionLocal | Fresh DB session opened per background task; request-scoped session never reused | DB session handle |
| run() → RuntimeError message (18-04) | Error message must not contain github_token value | Exception message string propagated to caller's logger.warning |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-18-01 | Information Disclosure | `codebase_scan_service.run()` — logging | mitigate | All `logger.*` calls (lines 46, 284, 299, 308, 314, 331, 334, 369, 373) format only `owner`, `repo`, `path`, `status_code`, `files_read` — `github_token` variable is interpolated only into the `Authorization` header dict (line 290), never into any logger call. Verified via `grep -n "logger\."` and `grep -n "github_token\|Authorization"` — zero overlap. | closed |
| T-18-02 | Tampering | `_select_key_files`, `_build_ascii_tree` — path handling | mitigate | `from pathlib import PurePosixPath` used at 8 call sites for name/extension parsing; zero `os.path.join`, `eval(`, or `exec(` occurrences anywhere in file (grep returned no matches). Paths used only as dict keys / string formatting / display tree nodes. | closed |
| T-18-03 | Information Disclosure | `_build_markdown` → PUT body | mitigate | PUT body `content` field is exclusively `base64.b64encode(markdown.encode()).decode()` (line 357); `put_body` dict contains only `message`, `content`, `branch`, optional `sha` — no credential or env var fields. | closed |
| T-18-04 | Denial of Service | Trees API response — large repos | accept | `MAX_FILES = 25` (line 36) enforced in `_select_key_files` (`selected[:MAX_FILES]`, line 126); `MAX_FILE_CHARS = 2000` (line 37) applied to all file content at lines 257, 337, 340; `truncated=true` branch logs a warning and continues (lines 313-314) rather than raising. Documented as accepted risk below. | closed (accepted) |
| T-18-SC (18-01) | Tampering | No new package installs | accept | `httpx==0.28.1` already present in `backend/requirements.txt` prior to this phase; no new entries added by plan 18-01. | closed (accepted) |
| T-18-05 | Information Disclosure | `_run_scan_background` — `decrypt_credential` usage | mitigate | `routers/projects.py` line 114: `github_token = decrypt_credential(bg_project.github_token)  # T-18-01: not logged`; token passed directly to `codebase_scan_service.run()` (line 117); the only `logger.*` call referencing the failure (`logger.warning("Codebase scan failed for project id=%s: %s", project_id, exc)`, line 119) logs `str(exc)` — and `exc` is the `RuntimeError` raised by `run()`, which is independently verified (T-18-04-01) to never interpolate `github_token`. No direct `logger.*` call in `projects.py` references the `github_token` variable. | closed |
| T-18-06 | Denial of Service | `asyncio.create_task` without await | accept | `asyncio.create_task(_run_scan_background())` (line 132) is fire-and-forget per the proven webhook.py pattern; the `except Exception` block inside `_run_scan_background` (lines 118-128) updates `PipelineState.status = "error"` and commits, preventing crash propagation to the event loop. | closed (accepted) |
| T-18-07 | Tampering | `PipelineState.ticket_key` sentinel `"__onboarding__"` | accept | `routers/projects.py` line 94: `ticket_key="__onboarding__"` is a hardcoded Python string literal, not derived from request payload; written via SQLAlchemy ORM (parameterized insert), eliminating SQL-injection risk. | closed (accepted) |
| T-18-SC (18-02) | Tampering | No new package installs | accept | `respx==0.23.1` and `pytest-asyncio==0.24.0` confirmed present in `backend/requirements.txt`; `asyncio` is a stdlib module. No new third-party packages introduced by plan 18-02. | closed (accepted) |
| T-18-03-01 | Tampering | test fixtures (monkeypatch target string) | accept | Test-only code in `backend/tests/test_projects.py` (`test_create_project_with_github_repo_schedules_scan_run`, line 342); an incorrect monkeypatch target string causes a test failure (fail-safe), not a production security exposure. No production code path affected. | closed (accepted) |
| T-18-04-01 | Information Disclosure | `RuntimeError` message in `run()` | mitigate | Both raise sites use only `owner`, `repo`, `status_code` in the f-string (lines 300-302, 309-311); regression tests `test_run_repo_metadata_non200_raises` and `test_run_trees_api_non200_raises` (`backend/tests/test_codebase_scan_service.py` lines 415-449) explicitly assert `"ghp_bad" not in str(exc_info.value)`. Both tests pass. | closed |
| T-18-04-02 | Tampering | `PipelineState.status` update in `_run_scan_background()` | accept | Update occurs inside the existing `try/except Exception` block (lines 118-129 of `routers/projects.py`) already covered by `db.commit()` semantics; no new code surface — confirmed by diff scope of plan 18-04 (only `codebase_scan_service.py` raise sites changed, `_run_scan_background` untouched). | closed (accepted) |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|--------------|------|
| AR-18-01 | T-18-04 | `MAX_FILES=25` and `MAX_FILE_CHARS=2000` bound memory/request count for large repos; `truncated=true` from GitHub Trees API logs a warning and the scan continues with a partial (but bounded) snapshot rather than failing. Residual risk: very large repos still produce 25 GitHub API round-trips per scan — acceptable given onboarding is a low-frequency, single-user-triggered event. | Phase 18 plan author (18-01-PLAN.md) | 2026-06-21 |
| AR-18-02 | T-18-SC (18-01) | No new pip packages installed in plan 18-01; `httpx` already vetted and present in `requirements.txt`. | Phase 18 plan author (18-01-PLAN.md) | 2026-06-21 |
| AR-18-03 | T-18-06 | `asyncio.create_task()` is fire-and-forget by design, matching the proven Phase 16-17 `webhook.py` background-task convention; task failures are caught and surfaced via `PipelineState.status="error"` rather than crashing the FastAPI event loop. | Phase 18 plan author (18-02-PLAN.md) | 2026-06-21 |
| AR-18-04 | T-18-07 | `ticket_key="__onboarding__"` is a hardcoded sentinel constant, never derived from user input; ORM parameterized insert eliminates injection risk. | Phase 18 plan author (18-02-PLAN.md) | 2026-06-21 |
| AR-18-05 | T-18-SC (18-02) | No new pip packages installed in plan 18-02; `respx` and `pytest-asyncio` already present in `requirements.txt`, `asyncio` is stdlib. | Phase 18 plan author (18-02-PLAN.md) | 2026-06-21 |
| AR-18-06 | T-18-03-01 | Test-only monkeypatch target string risk; incorrect target fails the test loudly (fail-safe) rather than silently passing — no production code path is affected. | Phase 18 plan author (18-03-PLAN.md) | 2026-06-21 |
| AR-18-07 | T-18-04-02 | `PipelineState.status` update in `_run_scan_background()` reuses pre-existing try/except/commit scaffolding from plan 18-02; plan 18-04 introduced no new surface in this function. | Phase 18 plan author (18-04-PLAN.md) | 2026-06-21 |

*Accepted risks do not resurface in future audit runs.*

---

## Unregistered Flags

None. Reviewed `## Threat Flags` sections in all four SUMMARY.md files (18-01, 18-02, 18-03, 18-04) — each explicitly states "None — no new network endpoints, auth paths, file access patterns, or schema changes beyond what the threat model already covers." No new attack surface requiring registration was identified by the executor during implementation.

---

## Verification Evidence Summary

| Check | Method | Result |
|-------|--------|--------|
| `github_token` never logged | `grep -n "logger\."` vs `grep -n "github_token\|Authorization"` cross-reference in `codebase_scan_service.py` | Zero overlap — confirmed |
| No `os.path.join`/`eval`/`exec` | `grep -n "os.path.join\|eval(\|exec("` | Zero matches |
| PUT body base64-only | `grep -n "base64.b64encode\|put_body"` | Confirmed at line 357 |
| `MAX_FILES`/`MAX_FILE_CHARS` enforced | `grep -n "MAX_FILES\|MAX_FILE_CHARS\|truncated"` | All cap sites confirmed (lines 36-37, 121, 126, 257, 313-314, 337, 340) |
| `httpx` pre-existing | `grep -n "^httpx" requirements.txt` | `httpx==0.28.1` present |
| `respx`/`pytest-asyncio` pre-existing | `grep -n "respx\|pytest-asyncio" requirements.txt` | Both present |
| RuntimeError messages exclude token | `grep -n "raise RuntimeError" -A2` + test assertions | Confirmed; tests assert `"ghp_bad" not in str(exc_info.value)` |
| `_run_scan_background` token handling | Manual read of `routers/projects.py` lines 105-130 | Token decrypted locally, passed only to `run()`, never logged directly |
| `ticket_key="__onboarding__"` hardcoded | `grep -n "__onboarding__"` | Confirmed literal at line 94 |
| Test suite passes | `python3 -m pytest tests/test_codebase_scan_service.py tests/test_projects.py -q` | 42 passed, 0 failed |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|----------------|--------|------|--------|
| 2026-06-22 | 12 | 12 | 0 | gsd-security-auditor |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-22
