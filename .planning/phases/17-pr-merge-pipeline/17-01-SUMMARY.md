---
phase: 17-pr-merge-pipeline
plan: "01"
subsystem: services
tags: [github-api, hermes, mcp, jira, pr-merge, status-transition]

requires:
  - phase: 15-github-config-dev-pipeline-foundation
    provides: github_token stored on Project model; pr_creator.py skeleton
  - phase: 16-dev-pipeline-integration
    provides: hermes_client.py, hermes/mcp_client.py, hermes/server.py patterns

provides:
  - "find_and_merge_pr(github_repo, github_token, issue_key, base_branch='main') -> MergeResult | None in backend/services/pr_creator.py"
  - "HermesMCPClient.transition_issue(issue_key, status_name, credentials) -> bool in hermes/mcp_client.py"
  - "POST /jira/status endpoint in hermes/server.py (TransitionIssueRequest Pydantic model)"
  - "async update_status(jira_url, jira_email, jira_token, issue_key, status_name) -> bool in backend/services/hermes_client.py"

affects: [17-02-pr-merge-pipeline]

tech-stack:
  added: []
  patterns: [TDD RED/GREEN per task, MergeResult dataclass, best-effort status update (never raises)]

key-files:
  created:
    - backend/services/pr_creator.py (MergeResult dataclass + find_and_merge_pr)
    - backend/tests/test_pr_creator.py
    - backend/tests/test_hermes_client.py
  modified:
    - hermes/mcp_client.py (transition_issue added)
    - hermes/server.py (POST /jira/status endpoint added)
    - backend/services/hermes_client.py (update_status added)

key-decisions:
  - "find_and_merge_pr returns None (not raises) when no open PR found for issue_key"
  - "PR match priority: head.ref == jarvis/issue-{key} first, then issue_key in title"
  - "transition_issue returns bool, never raises — matches update_status contract"
  - "github_token only in Authorization header, never in URLs or logs (T-17-01)"
  - "jira_token never logged in update_status (T-17-02)"
  - "transition_issue catches all exceptions, returns False (T-17-03)"

patterns-established:
  - "MergeResult dataclass: merged bool, sha, pr_number, pr_url fields"
  - "GitHub API: GET /repos/{owner}/{repo}/pulls?state=open then PUT .../pulls/{number}/merge"
  - "Best-effort wrappers: return False on any exception, never raise upstream"

requirements-completed: [PRMERGE-01, PRMERGE-02]

duration: 12min
completed: 2026-06-21
---

# Phase 17-01: PR Creator Primitives + Hermes Status Wiring

**Built the two reusable service-layer primitives that the `@jarvis merge pr` pipeline depends on: GitHub PR find/merge and Jira status-transition via Hermes MCP.**

## Performance

- **Duration:** 12 min
- **Completed:** 2026-06-21
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

### Task 1: `find_and_merge_pr()` in `backend/services/pr_creator.py`

- `MergeResult` dataclass with `merged`, `sha`, `pr_number`, `pr_url` fields
- Lists open PRs via `GET /repos/{owner}/{repo}/pulls?state=open`
- Matches by `head.ref == "jarvis/issue-{key}"` (preferred) or `issue_key in title` (fallback)
- Returns `None` if no matching open PR found
- Merges via `PUT .../pulls/{number}/merge`
- `github_token` only in `Authorization` header — never in URLs or logs (T-17-01)
- Tests: `test_pr_creator.py` covers success merge, no-PR-found (returns None), and title-fallback match

### Task 2: Hermes MCP status-transition support

- `HermesMCPClient.transition_issue(issue_key, status_name, credentials)` in `hermes/mcp_client.py`: calls `jira_transition_issue` MCP tool, returns `True/False`, never raises (T-17-03)
- `POST /jira/status` in `hermes/server.py`: `TransitionIssueRequest` Pydantic model, returns `{"success": bool}` — always 200
- `async update_status(jira_url, jira_email, jira_token, issue_key, status_name)` in `backend/services/hermes_client.py`: posts to `HERMES_BASE_URL/jira/status`, returns `False` on any error, logs `issue_key` only — `jira_token` never logged (T-17-02)

## Test Results

**36 backend + hermes tests pass** (34 backend + 2 hermes/tests/test_mcp_client.py new tests).  
11 pre-existing failures in `test_assign_pipeline.py` / `test_mcp_client.py` / `test_mcp_infra_smoke.py` confirmed pre-existing via `git stash` — unrelated to this phase.

## Self-Check: PASSED
