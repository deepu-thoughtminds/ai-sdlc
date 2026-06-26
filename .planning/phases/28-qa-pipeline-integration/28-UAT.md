---
status: complete
phase: 28-qa-pipeline-integration
source: [28-01-SUMMARY.md]
started: 2026-06-26T12:45:00Z
updated: 2026-06-26T12:45:00Z
---

## Current Test

## Current Test

[testing complete]

## Tests

### 1. Unit Tests Pass — No Regressions
expected: Run `cd backend && python -m pytest tests/test_qa_pipeline_e2e_wiring.py tests/test_app_container.py -v`. All 25 tests pass (5 wiring tests + 20 app_container tests), no failures.
result: pass

### 2. PLAYWRIGHT_BASE_URL Env Var No Longer Used
expected: In `backend/services/qa_pipeline.py`, the old `os.environ.get("PLAYWRIGHT_BASE_URL")` guard is gone. Search the file — the string `PLAYWRIGHT_BASE_URL` should not appear. The only source for the E2E URL is the `managed_app_container` context manager.
result: pass

### 3. E2E Skip on Container Failure — Pipeline Continues
expected: When the QA pipeline runs on a project that cannot start a container (e.g., no docker-compose.yml, or container start fails), E2E tests are skipped but unit/static analysis still run and the pipeline completes without crashing. The Jira comment appears without an E2E live URL.
result: pass

### 4. Live URL Appears in Jira Comment Header
expected: When the QA pipeline successfully starts a container, the E2E section header in the Jira comment reads `**E2E Tests (live: http://...):**` with the actual container URL. Without a live container, the header reads `**E2E Tests:**` (no `live:` marker).
result: pass

## Summary

total: 4
passed: 4
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
