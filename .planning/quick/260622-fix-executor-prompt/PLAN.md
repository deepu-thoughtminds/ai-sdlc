---
slug: fix-executor-prompt
date: 2026-06-22
status: in-progress
---

# Fix: claude_code_executor.py prompt to use codebase-memory-mcp properly

## Problem

The Hermes agent ran SCRUM-70 (a small text update on the login page) and:
1. Replaced 229-line `LoginPage.tsx` with a 42-line stub
2. Changed `export default function LoginPage()` → `export const LoginPage = ()` — breaking the default import in AppRouter.tsx
3. Changed `authAtom` (doesn't exist) instead of the correct `isAuthenticatedAtom`/`authUserAtom`
4. Navigated to `'/'` instead of `'/dashboard'` after login
5. This caused a blank white page in the test-blog application after the PR was merged

Root cause: The executor prompt told the agent to run `/gsd-quick` which launched a full GSD planning workflow, causing it to rewrite entire files from scratch instead of making targeted edits. The agent also didn't use `get_code_snippet` from codebase-memory-mcp to read the actual file content before changing it.

## Changes Required

### Task 1: Fix `backend/services/claude_code_executor.py`

Rewrite the prompt to:
- Step 1: Index repo with codebase-memory-mcp `index_repository` 
- Step 2: Use `search_graph` to find the specific file(s) relevant to the story
- Step 3: Use `get_code_snippet` to read the FULL content of each file to change
- Step 4: Use `search_code` to find ALL importers of each file being changed (to verify export compatibility)
- Step 5: Make TARGETED edits using the Edit tool — change ONLY the lines needed for the story
- Remove the `/gsd-quick` step — it causes full file rewrites
- Add explicit constraints: do NOT change export styles, do NOT change import names, do NOT rewrite entire files

### Task 2: Revert the bad LoginPage.tsx in test-blog

- The merged PR #11 (SCRUM-70) broke LoginPage.tsx
- We need to restore the original 229-line version in test-blog repo
- Commit the revert directly to main (it's an emergency fix for a broken production page)

## Acceptance Criteria

1. `claude_code_executor.py` prompt explicitly uses `get_code_snippet` before editing any file
2. Prompt explicitly forbids changing export styles or import names
3. Prompt does NOT instruct `/gsd-quick` usage
4. test-blog `src/pages/LoginPage.tsx` is restored to the full 229-line version with default export
5. test-blog `src/pages/LoginPage.test.tsx` is restored to the full 83-line test file
