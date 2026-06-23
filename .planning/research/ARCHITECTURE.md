# Architecture Research

**Domain:** Integration of Autonomous QA Stage into existing Jira-comment-driven AI SDLC pipeline (v1.8)
**Researched:** 2026-06-23
**Confidence:** HIGH (codebase-grounded: all integration points verified against existing modules)

## Standard Architecture

### System Overview

```
Jira webhook → FastAPI (webhook.py)
    → mention_parser.py (LLM intent router)
        ├── "run qa"   → asyncio.create_task(qa_pipeline.run())   [NEW]
        └── [existing routes: describe, architecture, start coding, merge pr]

merge_pipeline.py post-merge success path
    → asyncio.create_task(qa_pipeline.run())  [NEW auto-chain hook]

qa_pipeline.py  [NEW MODULE]
    → repo_clone.py  (reuse: clone github_repo to workspace)
    → codebase_scan_service.py  (reuse: read .hermes/codebase.md)
    → test_generator.py  [NEW: unit + static analysis + E2E test generation via freellmapi]
    → test_executor.py  [NEW: run generated tests in cloned workspace]
    → auto_fix_loop.py  [NEW: bounded retry — fix via codegen → re-run → check progress]
    → hermes_client.post_comment()  (reuse: post final pass/fail to Jira)
```

## Integration Points

### 1. Trigger Wiring (webhook.py + mention_parser.py)
- Add `"run_qa"` intent to LLM intent router; mention_parser extracts `intent="run_qa"` from `@jarvis run qa`
- webhook.py: add `elif stage == "run_qa"` branch; fire via `asyncio.create_task` (existing fire-and-forget pattern)
- Idempotency guard: same `PipelineState` check as architecture/merge — if active qa PipelineState exists for the ticket (status not failed), skip re-trigger

### 2. Auto-chain After Merge (merge_pipeline.py)
- At merge success path (after posting merge Jira comment): call `asyncio.create_task(qa_pipeline.run(project, issue_key))`
- Passes same `project` + `issue_key` already in scope; no new parameters needed
- This chain must be gated behind the same idempotency check to avoid race with manual `@jarvis run qa`

### 3. PipelineState Changes
- Add `stage="qa"` to the stage lifecycle (existing `PipelineState` model, no new table needed)
- Add `qa_attempt` integer column to track retry count per run (or store in `extra_data` JSON field if it exists)
- Status transitions: `"running"` → `"complete"` (all pass) | `"failed"` (retries exhausted)

### 4. QA Pipeline Module (qa_pipeline.py) — New
- Clone repo (reuse `repo_clone.py.clone_repo()`)
- Read `.hermes/codebase.md` (reuse `codebase_scan_service.get_codebase_summary()` or GitHub API fetch)
- Call `test_generator.generate()` → returns test files with FILE: convention (reuse `code_generator.py` output format)
- Write generated tests into the cloned workspace
- Run `test_executor.run_all()` — returns structured result (pass/fail counts, failure details)
- If failures → enter `auto_fix_loop.run()` up to MAX_QA_RETRIES (3)
- Post final result via `hermes_client.post_comment()`

### 5. Test Executor (test_executor.py) — New
- Detects toolchain per repo (Python → pytest; JS/TS → npm test / jest; playwright.config.* → Playwright)
- Runs commands via `subprocess.run()` in the cloned workspace with a hard timeout
- Returns structured `TestResult(passed, failed, errors, output_summary)`
- Playwright: requires `--no-sandbox` flag and `/dev/shm` sizing

### 6. Test Generator (test_generator.py) — New
- Uses `HermesLLMClient.chat()` (freellmapi) with codebase context + PR diff as prompt
- Generates: (a) unit test file(s), (b) static analysis commands, (c) Playwright E2E skeleton (if E2E infra detected)
- Output follows `### FILE: <path>\n<content>` convention (same as `code_generator.py`)

### 7. Auto-Fix Loop (auto_fix_loop.py) — New
- Input: `TestResult` (failing tests + error text), current workspace, codebase context
- Per iteration: generate targeted fix via `HermesLLMClient.chat()` with focused error context
- Apply fix to workspace (reuse `code_generator.apply_code_changes()`)
- Re-run `test_executor.run_all()` for failing tests only
- Terminate early: retries exhausted OR same error repeats (non-progress detection)
- After loop: open a new PR with auto-fixes via `pr_creator.py` (branch: `jarvis/qa-fix-{issue_key}`) — never commit to main

## New vs Modified Modules

| Module | Status | Notes |
|--------|--------|-------|
| `qa_pipeline.py` | NEW | Top-level orchestrator for QA stage |
| `test_generator.py` | NEW | LLM test generation via freellmapi |
| `test_executor.py` | NEW | Subprocess test execution + toolchain detection |
| `auto_fix_loop.py` | NEW | Bounded retry with non-progress detection |
| `webhook.py` | MODIFY | Add `run_qa` intent route + idempotency guard |
| `merge_pipeline.py` | MODIFY | Add auto-chain call at success path |
| `mention_parser.py` | MODIFY | Add `run_qa` to recognized intents |
| `PipelineState` model | MODIFY | Add `qa_attempt` tracking field |
| `docker-compose.yml` | MODIFY | Add `/dev/shm` sizing for Playwright execution |

## Suggested Build Order

1. **Phase 23: QA Foundation** — qa_pipeline.py skeleton, test_executor.py (toolchain detection + subprocess execution), PipelineState qa fields, static analysis only (no LLM yet)
2. **Phase 24: Test Generation** — test_generator.py (unit tests via freellmapi + PR diff context), write tests to workspace, execute, post result
3. **Phase 25: Auto-Fix Loop** — auto_fix_loop.py bounded retry, non-progress detection, PR creation for fixes
4. **Phase 26: E2E + Trigger Wiring** — Playwright E2E generation + detection, auto-chain from merge_pipeline.py, `@jarvis run qa` mention trigger, idempotency guard

## Key Risks

- **Sandbox isolation:** test_executor runs arbitrary repo code inside the backend container — highest-priority design decision (Phase 23)
- **Playwright Docker requirements:** headless Chromium needs `/dev/shm` ≥ 1GB and `--no-sandbox`; no Playwright infra exists today
- **Auto-fix loop creates new PRs:** must reuse `pr_creator.py` to preserve the human-review gate; never commit to main autonomously
