---
plan: 21-01
phase: 21
status: complete
requirements: [ARCHCTX-01, ARCHCTX-02]
---

# Summary: Thread codebase snapshot through architecture_pipeline and complexity_classifier

## What was built

Wired the `.hermes/codebase.md` snapshot (via `codebase_snapshot_reader.get_codebase_snapshot()`)
into the architecture pipeline. `architecture_pipeline.run()` now decrypts `project.github_repo`
and `project.github_token`, fetches the codebase snapshot exactly once, and passes it to both
`classify_complexity()` and the complexity-specific generation branches (`_run_complex()` /
`_run_simple()`). Architecture writeups and the complexity classification now reference actual
module names and file paths instead of inventing structure.

## Tasks completed

| Task | Status | Commits |
|------|--------|---------|
| 1. Thread codebase snapshot through architecture_pipeline.run() and complexity_classifier | complete | c5501b4 |
| 2. Update test suites to cover snapshot threading and prompt content | complete | 62bebeb |

## Key files changed

- `backend/services/architecture_pipeline.py` — added `from services.codebase_snapshot_reader import get_codebase_snapshot` import; `run()` decrypts `github_repo`/`github_token` (try/except, warnings on failure, decrypted values never logged — T-21-01) and calls `get_codebase_snapshot()` exactly once; passes `codebase_snapshot=snapshot` to `classify_complexity()`; passes `snapshot` to `_run_complex()`/`_run_simple()`; both branches inject `snapshot[:8000]` (or `"(no codebase context available)"` fallback — T-21-02) into the architecture LLM prompt with an instruction to reference real module/file names
- `backend/services/complexity_classifier.py` — `_build_classify_prompt()` and `classify_complexity()` accept optional `codebase_snapshot: str | None = None`; when provided, appended (truncated to 8000 chars) to the classification prompt; isolation contract preserved (module still does not import `get_codebase_snapshot` itself)
- `backend/tests/test_architecture_pipeline.py` — `_make_mock_project()` adds encrypted `github_repo`/`github_token`; all 7 existing `run()` tests patch `services.architecture_pipeline.get_codebase_snapshot` as `AsyncMock`; added `test_run_includes_snapshot_in_architecture_prompt` and `test_run_passes_snapshot_to_complexity_classifier`
- `backend/tests/test_complexity_classifier.py` — added `test_build_classify_prompt_includes_snapshot_when_provided`, `test_build_classify_prompt_no_snapshot_when_none`, `test_classify_complexity_passes_snapshot_to_prompt`

## Acceptance criteria verified

- [x] `architecture_pipeline.run()` calls `get_codebase_snapshot()` exactly once (single `await` call site; 0 occurrences inside `_run_complex`/`_run_simple` bodies — verified via grep)
- [x] Snapshot passed as `codebase_snapshot=snapshot` to `classify_complexity()` and as a positional param to `_run_complex()`/`_run_simple()`
- [x] `complexity_classifier.classify_complexity()` / `_build_classify_prompt()` accept optional `codebase_snapshot`; appended (8000-char truncated) to prompt when provided
- [x] Snapshot None → `"(no codebase context available)"` fallback text used in both prompts; pipeline continues without error
- [x] github_token/github_repo decrypted values never appear in any `logger.*` call in `architecture_pipeline.py` — only `issue_key` and exception text logged
- [x] Decrypt failures logged as warnings; pipeline continues with empty strings (no crash)
- [x] All 18 tests pass (9 in `test_architecture_pipeline.py`, 9 in `test_complexity_classifier.py`)
- [x] No regressions: full backend suite run; 5 pre-existing unrelated failures (`test_assign_pipeline.py` x4, `test_repo_clone.py` x1) confirmed pre-existing via `git stash` comparison — untouched by this plan

## Self-Check: PASSED

All structural and behavioral checks from the plan's `<verification>` section pass:
- `grep` confirms `get_codebase_snapshot` imported in `architecture_pipeline.py`
- `grep` confirms `codebase_snapshot` parameter present in `complexity_classifier.py`
- `get_codebase_snapshot` appears exactly once as an executable call (the `await` in `run()`); the other two matches are the import line and a docstring mention
- `get_codebase_snapshot` does NOT appear inside `_run_complex` or `_run_simple` function bodies
- 18/18 new and existing tests pass; 257 passed / 5 pre-existing unrelated failures / 3 skipped across the full backend suite
