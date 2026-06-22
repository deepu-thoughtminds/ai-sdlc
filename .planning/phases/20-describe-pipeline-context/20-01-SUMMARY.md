---
plan: 20-01
phase: 20
status: complete
requirements: [DESCCTX-01, DESCCTX-02]
---

# Summary: Replace graphify_service with get_codebase_snapshot in describe_pipeline

## What was built

Wired the Phase 19 codebase snapshot reader into `describe_pipeline.py`, replacing the old
`graphify_service.get_codebase_summary()` with `codebase_snapshot_reader.get_codebase_snapshot()`.
Story elaborations produced by `@jarvis describe` now reference real module names and file paths
from the committed `.hermes/codebase.md` snapshot instead of generic placeholders.

## Tasks completed

| Task | Status | Commits |
|------|--------|---------|
| 1. TDD: failing tests → implementation → passing tests | complete | d0a4044, 4deb016 |

## Key files changed

- `backend/services/describe_pipeline.py` — removed `graphify_service` import; added `get_codebase_snapshot` import and `await` call with decrypted `github_repo`; updated prompt to inject snapshot text (truncated 8000 chars); updated module docstring with DESCCTX-01/DESCCTX-02 and T-20-01/T-20-02 threat notes
- `backend/tests/test_describe_pipeline.py` — replaced all `get_codebase_summary` patches with `get_codebase_snapshot` AsyncMock; removed `_make_stub_summary()`; added `project.github_repo` encrypted field to mock project; added `test_run_includes_snapshot_content_in_prompt` verifying DESCCTX-02

## Acceptance criteria verified

- [x] `from services.codebase_snapshot_reader import get_codebase_snapshot` present in describe_pipeline.py
- [x] `graphify` removed from describe_pipeline.py code (only in docstring comment)
- [x] `get_codebase_snapshot` used at import and `await` call sites
- [x] `github_repo` decrypted via `decrypt_credential()`; never appears in any `logger.*` call
- [x] `test_run_includes_snapshot_content_in_prompt` present and passing
- [x] All 4 describe_pipeline tests pass
- [x] No regressions (pre-existing `test_assign_pipeline_calls_lookup_user` failure is unrelated)

## Self-Check: PASSED

All 4 describe_pipeline tests pass. Implementation matches the plan's behavior spec exactly.
Pre-existing failure in `test_assign_pipeline` confirmed pre-existing before this plan.
