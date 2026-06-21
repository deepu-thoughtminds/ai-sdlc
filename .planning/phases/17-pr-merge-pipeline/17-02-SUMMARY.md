---
phase: 17-pr-merge-pipeline
plan: "02"
subsystem: services, routers
tags: [merge-pipeline, webhook, orchestrator, idempotency, async, jira, github]

requires:
  - phase: 17-01-pr-merge-pipeline
    provides: find_and_merge_pr, update_status, transition_issue, POST /jira/status
  - phase: 16-dev-pipeline-integration
    provides: dev_pipeline.py orchestrator pattern (idempotency guard, CR-02, WR-01, WR-03)

provides:
  - "backend/services/merge_pipeline.py: async run() orchestrator wiring find_and_merge_pr + update_status + hermes_post_comment with graceful degradation"
  - "backend/routers/webhook.py: merge_pr branch with idempotency guard + PipelineState(stage='merge_pr') + asyncio.create_task(_run_merge_background())"

affects: []

tech-stack:
  added: []
  patterns: [idempotency guard (PipelineState status check), CR-02 session isolation, WR-01 post-comment-before-complete, WR-03 best-effort failure notification, asyncio.create_task fire-and-forget]

key-files:
  created:
    - backend/services/merge_pipeline.py
    - backend/tests/test_merge_pipeline.py
  modified:
    - backend/routers/webhook.py (merge_pr stub replaced)
    - backend/tests/test_webhook.py (merge_pr stub test replaced with 3 wiring tests)

key-decisions:
  - "merge_pipeline.py follows dev_pipeline.py pattern exactly (idempotency, CR-02, WR-01, WR-03)"
  - "Graceful degradation: no-PR-found posts informative comment then returns (not an error)"
  - "Status-update failure (update_status returns False) is non-fatal — merge still posts success comment"
  - "webhook.py merge_pr branch mirrors start_coding/architecture branches (PipelineState + create_task)"
  - "Threat mitigations T-17-05 through T-17-09 applied (token never in logs, session isolation, idempotency, failure notification)"

patterns-established:
  - "merge_pipeline.run() pattern: idempotency guard → find_and_merge_pr → update_status (best-effort) → hermes_post_comment"
  - "webhook merge_pr: status != running/complete check → PipelineState(running) → create_task(_run_merge_background)"

requirements-completed: [PRMERGE-01, PRMERGE-02]

duration: 11min
completed: 2026-06-21
---

# Phase 17-02: Merge Pipeline Orchestrator + Webhook Wiring

**Wired `@jarvis merge pr` end-to-end: `merge_pipeline.py` orchestrator delegates to Wave 1 primitives, and webhook.py routes the `merge_pr` intent through the same idempotency-guarded fire-and-forget pattern used by start_coding and architecture.**

## Performance

- **Duration:** 11 min
- **Completed:** 2026-06-21
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

### Task 1: `merge_pipeline.py` orchestrator

- `async run(project, issue_key, db)` — 218-line async orchestrator
- Idempotency guard: checks `PipelineState(stage='merge_pr', status__in=['running','complete'])` before proceeding
- Creates `PipelineState(stage='merge_pr', status='running')` before `asyncio.create_task`
- Calls `find_and_merge_pr()` → on `None` (no PR found): posts informative Jira comment, returns
- Calls `update_status()` (best-effort, failure is non-fatal)
- Calls `hermes_post_comment()` with merge commit URL (WR-01)
- On exception: calls `hermes_post_comment()` with failure notice (WR-03), updates PipelineState to `failed`
- Uses CR-02 session isolation (fresh db session in background task)
- 6 TDD tests covering success path, no-PR-found, merge failure, and status-update failure

### Task 2: webhook.py `merge_pr` stub replacement

- Replaced `routed_to: "pending_phase_17"` stub with real wiring
- Pattern mirrors `start_coding` and `architecture` branches exactly
- Idempotency guard → `PipelineState(stage='merge_pr', status='running')` → `asyncio.create_task(_run_merge_background())`
- Added `merge_pipeline` to services imports
- 3 new webhook tests: success routing, duplicate-ignored, merge_pipeline.run called with correct args

## Test Results

**256 tests pass** across backend and hermes (up from 248 after Wave 1 — 8 new tests from 17-02 all pass).  
11 pre-existing failures confirmed unrelated to this phase (same set as at base commit).

## Self-Check: PASSED
