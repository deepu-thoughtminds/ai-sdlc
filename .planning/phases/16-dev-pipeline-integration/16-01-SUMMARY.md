---
phase: 16-dev-pipeline-integration
plan: "01"
subsystem: hermes-mcp-client / backend-hermes-client / confluence-url-finder
tags: [mcp, jira, confluence, hermes, tdd, devpipe]
dependency_graph:
  requires: []
  provides:
    - hermes.mcp_client.HermesMCPClient.get_comments
    - hermes.mcp_client.HermesMCPClient.get_confluence_page
    - hermes.server.POST /jira/comments
    - hermes.server.GET /confluence/page/{page_id}
    - backend.services.hermes_client.get_comments
    - backend.services.hermes_client.get_confluence_page_content
    - backend.services.confluence_url_finder.find_latest_architecture_url
  affects:
    - backend/services/dev_pipeline.py (future plan 02)
tech_stack:
  added: []
  patterns:
    - Triple-nested streamablehttp_client/ClientSession/call_tool MCP call pattern
    - Normalised-return convention (never raw MCP envelope)
    - Degrade-to-[]/"" on error for pipeline-critical fetch functions
    - Pure function utility (no I/O, only stdlib re)
    - Newest-first comment iteration for most-recent URL extraction
key_files:
  created:
    - backend/services/confluence_url_finder.py
    - backend/tests/test_confluence_url_finder.py
  modified:
    - hermes/mcp_client.py
    - hermes/server.py
    - hermes/tests/test_mcp_client.py
    - hermes/tests/test_server.py
    - backend/services/hermes_client.py
    - backend/tests/test_hermes_client.py
decisions:
  - "POST /jira/comments used instead of GET to avoid exposing jira_token in URL query parameters"
  - "GET /confluence/page/{page_id} wraps body in {body: str} envelope to align with hermes sentinel pattern"
  - "get_comments uses jira_get_issue with fields=comment (not a dedicated jira_get_comments tool)"
  - "get_confluence_page uses confluence_get_page returning body.storage.value plain string"
  - "CONFLUENCE_URL_PATTERN anchors on /wiki/spaces/*/pages/<numeric-id> to avoid non-Confluence matches"
  - "confluence_url_finder iterates reversed(comments) because Jira returns oldest-first order"
metrics:
  duration: "6m 32s"
  completed_date: "2026-06-21"
  tasks_completed: 2
  tasks_total: 2
  files_created: 2
  files_modified: 6
---

# Phase 16 Plan 01: Comment History Fetch and Confluence URL Extraction Summary

**One-liner:** Jira comment fetch (get_comments) and Confluence page body fetch (get_confluence_page) wired through HermesMCPClient, hermes server endpoints, and backend hermes_client wrappers; pure `find_latest_architecture_url` scans comment history newest-first with regex CONFLUENCE_URL_PATTERN.

## Tasks Completed

| Task | Description | Commit | Key Files |
|------|-------------|--------|-----------|
| 1 | Add get_comments and get_confluence_page to HermesMCPClient + server endpoints | 58d6261 | hermes/mcp_client.py, hermes/server.py, hermes/tests/test_mcp_client.py, hermes/tests/test_server.py |
| 2 | Add backend hermes_client wrappers + confluence_url_finder utility | 4d31d28 | backend/services/hermes_client.py, backend/services/confluence_url_finder.py, backend/tests/ |

## What Was Built

### Task 1: HermesMCPClient + Hermes Server

**`hermes/mcp_client.py`** — Two new methods on `HermesMCPClient`:

- `get_comments(issue_key, credentials) -> list[dict]`: Calls `jira_get_issue` MCP tool with `fields="comment"`. Extracts flat list from `fields.comment.comments` envelope. Returns `[]` on empty. Uses Jira credential headers (`x-atlassian-jira-url`).

- `get_confluence_page(page_id, credentials) -> str`: Calls `confluence_get_page` MCP tool with `page_id`. Extracts plain string from `body.storage.value`. Returns `""` on missing field. Uses Confluence credential headers (`x-atlassian-confluence-url`).

Both follow the normalised-return convention established in the codebase — never return the raw MCP envelope.

**`hermes/server.py`** — Two new endpoints:

- `POST /jira/comments` (`post_get_comments`) — Request body carries credentials to avoid token exposure in URLs. Returns flat list from `get_comments()`.

- `GET /confluence/page/{page_id}` (`get_confluence_page`) — Credentials as query params (mirrors `GET /confluence/search`). Returns `{"body": "<content>"}` wrapper.

### Task 2: Backend Wrappers + Pure Utility

**`backend/services/hermes_client.py`** — Two new functions:

- `get_comments(jira_url, jira_email, jira_token, issue_key) -> list[dict]`: POSTs to `HERMES_BASE_URL/jira/comments`. Degrades to `[]` on any error. T-09-01: jira_token never logged.

- `get_confluence_page_content(confluence_url, confluence_email, confluence_token, page_id) -> str`: GETs `HERMES_BASE_URL/confluence/page/{page_id}`. Degrades to `""` on any error. Unwraps `{"body": str}` envelope. T-04-05: confluence_token never logged.

**`backend/services/confluence_url_finder.py`** — New pure utility module:

- `CONFLUENCE_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+/wiki/spaces/[^\s<>\"'/]+/pages/\d+")` — matches both atlassian.net cloud and self-hosted Confluence.

- `find_latest_architecture_url(comments: list[dict]) -> str | None` — iterates `reversed(comments)` (Jira oldest-first to newest-first scan), skips non-string/missing body, returns first match or `None`.

## Test Coverage

| Test file | New tests | Result |
|-----------|-----------|--------|
| hermes/tests/test_mcp_client.py | 8 (get_comments + get_confluence_page) | 8 passed |
| hermes/tests/test_server.py | 9 (POST /jira/comments + GET /confluence/page/{id}) | 9 passed |
| backend/tests/test_hermes_client.py | 7 (get_comments + get_confluence_page_content) | 7 passed |
| backend/tests/test_confluence_url_finder.py | 13 (all url_finder cases) | 13 passed |

Total new: **37 tests**, all passing.

Pre-existing failures in `hermes/tests/test_mcp_client.py` (5): `test_add_comment_calls_correct_tool`, `test_add_comment_maps_credentials`, `test_update_description_calls_correct_tool`, `test_lookup_user_returns_account_id`, `test_assign_issue_calls_correct_tool` — these existed before this plan (tool name/arg name mismatches). Out of scope per deviation scope boundary.

## Decisions Made

1. **POST /jira/comments instead of GET** — Jira token must not appear in URL query parameters (T-09-01). Using POST body keeps credentials out of request logs and HTTP access logs.

2. **GET /confluence/page/{page_id} wraps body in `{"body": str}`** — Consistent with hermes sentinel pattern (hermes GET endpoints return structured JSON). Avoids returning raw strings from FastAPI which could cause content-type confusion.

3. **`jira_get_issue` with `fields="comment"` for get_comments** — The mcp-atlassian toolset does not expose a dedicated `jira_get_comments` tool; `jira_get_issue` with fields filtering is the canonical approach.

4. **`confluence_get_page` for get_confluence_page** — Returns the full page object including `body.storage.value`; the method normalises this to a plain string for the codegen prompt context.

5. **`CONFLUENCE_URL_PATTERN` anchored on `/wiki/spaces/.../pages/<digits>`** — Rejects github.com, docs.example.com, notion.so etc.; the numeric page-id suffix ensures only true Confluence page URLs match.

6. **`reversed(comments)` in confluence_url_finder** — Jira's REST API returns comments in creation order (oldest first). Reversing ensures the most recently posted architecture URL is returned when the team has updated it multiple times.

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all functions return real data from the MCP/HTTP call or degrade to empty sentinel values (`[]`/`""`) with logged warnings.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: credential_in_query_param | hermes/server.py GET /confluence/page/{page_id} | Confluence credentials passed as URL query params — acceptable for internal container-to-container calls (same network), but would be a risk over public internet. This matches the pre-existing GET /confluence/search pattern. |

## Self-Check: PASSED

Files exist:
- FOUND: backend/services/confluence_url_finder.py
- FOUND: backend/services/hermes_client.py (get_comments, get_confluence_page_content)
- FOUND: hermes/mcp_client.py (get_comments, get_confluence_page)
- FOUND: hermes/server.py (post_get_comments, get_confluence_page)

Commits exist:
- 58d6261: feat(16-01): add get_comments and get_confluence_page to HermesMCPClient and server
- 4d31d28: feat(16-01): add get_comments, get_confluence_page_content wrappers and confluence_url_finder
