---
slug: fix-executor-prompt
date: 2026-06-22
status: complete
---

# Summary: Fix executor prompt + revert LoginPage.tsx

## What was wrong

PR #11 (jarvis/issue-SCRUM-70) merged into deepu-thoughtminds/test-blog caused a blank white page.

Root cause audit of `LoginPage.tsx` changes:
1. **Export style broken** — `export default function LoginPage()` → `export const LoginPage = ()`. AppRouter.tsx does `import LoginPage from '../pages/LoginPage'` (default), so it got `undefined` → blank page.
2. **Non-existent atom** — `authAtom` imported instead of `isAuthenticatedAtom`/`authUserAtom` (runtime error).
3. **Wrong navigation** — `navigate('/')` instead of `navigate('/dashboard')`.
4. **Full file rewrite** — 229 lines replaced with 42-line stub, stripping all login form functionality.

Root cause in executor: The prompt said `Run /gsd-quick` which launches a full GSD planning cycle, causing the agent to rewrite the file from a blank-slate template rather than make a surgical edit to the existing code.

## Changes made

### `backend/services/claude_code_executor.py`
- Removed `/gsd-quick` instruction from prompt
- Added CRITICAL RULES block: no full-file rewrites, no export style changes, no atom renames
- Added explicit 6-step sequence: INDEX → FIND FILES → READ EXACT CONTENT (get_code_snippet) → FIND IMPORTERS (search_code) → TARGETED EDIT → VERIFY
- Committed: `151a578`

### `test-blog/src/pages/LoginPage.tsx`
- Restored to pre-SCRUM-70 229-line version from commit 4fd9982
- Default export preserved, correct atoms used, correct navigation restored
- Committed: `3fc773b` (test-blog repo)

### `test-blog/src/pages/LoginPage.test.tsx`
- Restored to pre-SCRUM-70 83-line version (6 full test cases)
- Committed alongside LoginPage.tsx

## Architecture blank page

Separate issue — not addressed in this task. The architecture pipeline uses `_render_diagram_template` / `_render_text_only_template` in `confluence_client.py`. If Confluence shows a blank page, likely the LLM returned empty sections that passed through to the HTML template. Needs investigation of the `_parse_sections` output for the specific ticket.
