---
plan: "35-01"
phase: "35"
title: "Dev Pipeline: opencode CLI + cbm graph context migration"
status: complete
self_check: PASSED
completed_at: "2026-07-01"
---

## What Was Built

Migrated `dev_pipeline.py` from the old GitHub snapshot approach (`get_codebase_summary` + `github_url`) to the codebase-memory-mcp graph pattern already proven in `describe_pipeline.py` and `architecture_pipeline.py`. Also renamed `directory_tree` → `codebase_context` in `agentic_coder.py` and updated all tests.

## Key Files

### Created
- `.planning/phases/35-dev-pipeline/35-01-SUMMARY.md` — this file

### Modified
- `backend/services/dev_pipeline.py` — added `_query_dev_context()` async fn using `cbm_call('search_graph', ...)`; replaced `get_codebase_summary` import and `github_url` derivation block; passes `graph_text` to `run_agentic_codegen()` and `generate_playwright_config()`
- `backend/services/agentic_coder.py` — renamed `directory_tree` param → `codebase_context`; renamed `_MAX_DIRECTORY_TREE_CHARS` → `_MAX_CODEBASE_CONTEXT_CHARS`; updated prompt label to `Codebase context (module graph):`
- `backend/tests/test_dev_pipeline.py` — replaced all `get_codebase_summary` patches with `_query_dev_context` AsyncMock patches; rewrote `test_run_derives_github_url_from_repo_when_missing` → `test_run_uses_cbm_graph_context`

## Commits

1. `6d36f93` feat(35-01): replace get_codebase_summary with cbm graph context in dev_pipeline
2. `67b55cb` refactor(35-01): rename directory_tree to codebase_context in agentic_coder
3. `e9caa92` test(35-01): replace get_codebase_summary patches with _query_dev_context mocks

## Decisions

- `_query_dev_context()` follows the exact same pattern as `_query_describe_context()` in `describe_pipeline.py` — `cbm_call('search_graph', {'query': f'{issue_key} {issue_summary}', 'limit': 20})`
- CTX-04 satisfied: `cbm_call` is invoked before `clone_repository()` and no credentials are passed to it

## Self-Check

- [x] `dev_pipeline.py` imports `cbm_call` from `services.cbm_client`, NOT `get_codebase_summary`
- [x] `_query_dev_context()` exists and calls `cbm_call('search_graph', ...)`
- [x] `_query_dev_context()` called before `clone_repository()` in `run()`
- [x] `run_agentic_codegen()` receives `graph_text` as `codebase_context` param
- [x] `agentic_coder.py` param named `codebase_context`, label `Codebase context (module graph):`
- [x] All 9 tests pass without patching `get_codebase_summary`
