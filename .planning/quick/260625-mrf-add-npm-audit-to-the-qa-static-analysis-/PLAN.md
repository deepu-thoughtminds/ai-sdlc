---
task: Add npm audit auto-fix PR to QA pipeline
slug: add-npm-audit-to-the-qa-static-analysis-
date: 2026-06-25
---

# Task: npm audit auto-fix PR

npm_audit already runs in `run_static_analysis` (services/test_executor.py). When it fails,
add an auto-fix step that runs `npm audit fix` in Docker, detects changed files, and opens a PR.

## Files to touch

- `services/test_executor.py` — add `run_npm_audit_fix()` function
- `services/qa_pipeline.py` — call it after static analysis, report PR URL

## Implementation

### 1. `services/test_executor.py` — add `run_npm_audit_fix()`

```python
def run_npm_audit_fix(
    workspace_path: str,
    timeout: int = 300,
) -> list[str]:
    """Run `npm audit fix` in Docker; return list of relative paths that changed.

    Returns empty list if nothing changed or if the workspace has no package.json.
    Uses same Docker image as the npm_audit toolchain command (node:20-slim).
    T-23-01: list-form args, no shell=True.
    """
```

Steps inside:
1. Detect `package.json` — return [] if absent
2. Detect lockfile type (npm/yarn/pnpm), build install+fix command
3. Run Docker with workspace bind-mount (same pattern as detect_toolchain)
4. After Docker exits, run `git -C workspace_path diff --name-only` to find changed files
5. Return relative paths of changed files ([] if none)

### 2. `services/qa_pipeline.py` — wire up after static analysis

After `static_results = run_static_analysis(...)`:

```python
npm_audit_fix_pr_url: str | None = None
npm_audit_failed = any(
    r.tool == "npm_audit" and r.returncode != 0 and not r.timed_out
    for r in static_results
)
if npm_audit_failed:
    changed_paths = run_npm_audit_fix(cloned.workspace_path)
    if changed_paths:
        file_changes = [
            FileChange(
                path=p,
                content=pathlib.Path(cloned.workspace_path, p).read_text(errors="replace"),
            )
            for p in changed_paths
        ]
        try:
            pr = apply_commit_push_and_open_pr(
                cloned.workspace_path,
                github_repo,
                github_token,
                issue_key,
                file_changes,
                pr_title=f"fix: npm audit fix for {issue_key}",
                pr_body=f"Auto-fix for npm audit vulnerabilities detected in {issue_key}.",
                branch_name=f"jarvis/npm-audit-fix-{issue_key}",
            )
            npm_audit_fix_pr_url = pr.html_url
        except Exception:
            logger.exception("npm audit fix PR creation failed for %s", issue_key)
```

Add `npm_audit_fix_pr_url` to `_format_qa_comment` output and pass to `_build_remediation_html`.

### 3. Imports needed in qa_pipeline.py

```python
import pathlib
from services.code_generator import FileChange
from services.pr_creator import apply_commit_push_and_open_pr
from services.test_executor import run_npm_audit_fix
```

## Commit

Single atomic commit: "feat: npm audit auto-fix PR on QA vulnerability detection"
