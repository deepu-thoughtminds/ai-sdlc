---
slug: playwright-python-e2e
created: 2026-06-26
status: in_progress
---

# Quick Task: Python Playwright E2E via Claude Code CLI

## Goal
Generate Python Playwright scripts using Claude Code CLI during QA pipeline, execute them, and include results in the QA report (Jira comment + Confluence page).

## Tasks

### 1. Add `run_claude_playwright_generator` to `claude_code_executor.py`
- New function that invokes `claude` CLI with a prompt to generate a Python Playwright test file evaluating the code changes
- Prompt includes: issue description, architecture content, code changes (diff or file contents)
- Parses `### FILE:` convention output to extract test file paths and content
- Returns `list[FileChange]`

### 2. Update `qa_pipeline.py` — add Python Playwright evaluation stage
- After existing e2e_results block, add new `playwright_py_results` list
- Gate on `CLAUDE_API_KEY` env var being set (mirrors claude_code_executor.py pattern)
- Call `run_claude_playwright_generator(...)` to get Python test files
- Write files to workspace (with T-24-01 path traversal guard)
- Execute via Docker: `docker run --rm -v workspace:/workspace qa-sandbox python -m pytest <file> --tb=short`  
  (qa-sandbox already has playwright installed; Python playwright uses pytest-playwright)
- Collect `TestResult` objects

### 3. Update `_format_qa_comment` — add Python Playwright section
- New "**Python Playwright Evaluation:**" section after E2E Tests
- Same pass/fail/timed-out formatting as unit tests

### 4. Update `_build_remediation_html` — include playwright_py_failures
- Add playwright_py_failures to the remediation items list

### 5. Thread `playwright_py_results` through all callers
- `_format_qa_comment(...)` signature
- `_build_remediation_html(...)` signature  
- `publish_qa_report(...)` call site

## Files to touch
- `backend/services/claude_code_executor.py` — add generator function
- `backend/services/qa_pipeline.py` — wire new stage + update formatting
