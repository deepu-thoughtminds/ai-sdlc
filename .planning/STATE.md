---
gsd_state_version: 1.0
milestone: v1.6
milestone_name: Context-Aware Codebase Scanning
current_phase: 21
current_phase_name: architecture-pipeline-context
status: executing
stopped_at: context exhaustion at 75% (2026-06-22)
last_updated: "2026-06-22T13:33:15.355Z"
last_activity: 2026-06-22
last_activity_desc: Phase 21 plan 01 executed and complete
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 8
  completed_plans: 8
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-21)

**Core value:** Team members trigger AI-powered SDLC automation directly from Jira comment history, with every output linked back to the originating ticket.
**Current focus:** Phase 21 — architecture-pipeline-context

## Current Position

Phase: 21 (architecture-pipeline-context) — COMPLETE
Plan: 1 of 1 (complete)
Status: Phase 21 complete — milestone v1.6 (Context-Aware Codebase Scanning) all 4 phases done
Last activity: 2026-06-22 -- Phase 21 plan 01 executed and complete

## Milestone History

| Milestone | Phases | Plans | Status | Completed |
|-----------|--------|-------|--------|-----------|
| v1.0 | 4 | 8 | Complete | 2026-06-18 |
| v1.1 freellmapi | 1 (Phase 5) | 2 | Complete | 2026-06-18 |
| v1.2 hermes-freellmapi | 1 (Phase 6) | 2 | Complete | 2026-06-18 |
| v1.3 hermes-mcp-agent | 3 (Phases 7-9) | 3 | Complete | 2026-06-19 |
| v1.4 smart-architecture | 4 (Phases 10-13) | 2026-06-19 | Complete | All 13 phases, all 24 plans done |
| v1.5 github-dev-pipeline | 4 (Phases 14-17) | TBD | Complete | 2026-06-21 |
| v1.6 context-aware-codebase-scanning | 4 (Phases 18-21) | 8 | Complete | 2026-06-22 |

## Performance Metrics

**Velocity:**

- Total plans completed: 21
- Average duration: ~12 min/plan
- Total execution time: ~144 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-foundation | 2 | ~28 min | ~14 min |
| 02-web-app | 2 | ~20 min | ~10 min |
| 03-description-elaboration | 2 | ~14 min | ~7 min |
| 04-architecture-pipeline | 2 | ~16 min | ~8 min |
| 05-freellmapi-integration | 2 | ~6 min | ~3 min |
| 06-hermes-llm-client | 2 | ~6 min | ~3 min |
| 15 | 2 | - | - |
| 17 | 2 | - | - |
| 18 | 4 | - | - |
| 20 | 1 | - | - |

**Recent Trend:**

- Last 5 plans: 04-02 (8 min), 05-01 (?), 05-02 (3 min), 06-01 (?), 06-02 (3 min)
- Trend: on track

*Updated after each plan completion*

| Phase 02-web-app P01 | 10 | 2 tasks | 13 files |
| Phase 03-description-elaboration P01 | 8min | 2 tasks | 14 files |
| Phase 03-description-elaboration P02 | 6min | 2 tasks | 6 files |
| Phase 04-architecture-pipeline P02 | 8min | 2 tasks | 4 files |
| Phase 05-freellmapi-integration P02 | 3min | 3 tasks | 3 files |
| Phase 06-hermes-llm-client P02 | 3 | 2 tasks | 5 files |
| Phase 10 P01 | 2min | 3 tasks | 3 files |
| Phase 11 P01 | 2min | 2 tasks | 2 files |
| Phase 12-structured-confluence-publishing P01 | 18 min | 1 tasks | 2 files |
| Phase 13 P01 | 8 | 1 tasks | 1 files |
| Phase 13 P02 | 9min | 2 tasks | 5 files |
| Phase 18-codebase-scan-service P04 | 8 | 2 tasks | 2 files |
| Phase 19-snapshot-refresh-read-fallback P01 | 3min | 1 tasks | 2 files |
| Phase 19-snapshot-refresh-read-fallback P02 | 2min | 1 tasks | 2 files |
| Phase 21-architecture-pipeline-context P01 | - | 2 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Jira webhook (not polling) for real-time trigger — no overhead
- freellmapi handles all heavy LLM tasks to control cost
- v1 scope = description elaboration + architecture stages only
- JIRA_WEBHOOK_SECRET optional env var — skips check if unset (dev-friendly; production must set it)
- freellmapi httpx call is best-effort; stub fallback on connection error
- KNOWN_STAGES whitelist lives in mention_parser (single gate before llm_router)
- [Phase ?]: StaticPool for test SQLite: each sqlite:///:memory: connection is isolated; StaticPool shares one connection across threads
- [Phase ?]: Lazy Fernet key read in crypto.py: reads ENCRYPTION_KEY per call not module-level
- [Phase 03-01]: github_url added as nullable column to Project model — no migration needed (SQLite nullable column is backward compatible)
- [Phase 03-01]: respx 0.23.1 used instead of 0.21.1 — compatible API, already installed system-wide
- [Phase 03-01]: Ollama /api/chat native format replaces OpenAI-compat /v1/chat/completions in llm_router — reversed in Phase 05
- [Phase ?]: JiraClient calls inside async webhook handler are synchronous (httpx.Client) — no asyncio.to_thread wrapper needed for MVP
- [Phase ?]: test_webhook.py DB override moved from module-level to reset_tables fixture to prevent cross-test contamination across test modules
- [Phase ?]: Architecture approval uses add_comment not update_description — posts draft_content as new comment
- [Phase ?]: detect_and_apply_approval kept existing (event, db, project) signature for backward compatibility
- [Phase ?]: Webhook architecture routing uses asyncio.create_task (fire-and-forget) for heavy LLM calls
- [Phase 05]: freellmapi (tashfeenahmed/freellmapi) is Node.js/npm, not the codefuse-ai image; added as git submodule at ./freellmapi/
- [Phase 05]: llm_router switches from /api/chat (Ollama) to /v1/chat/completions (OpenAI-compat) with Bearer token; response parsing changes from data["message"]["content"] to data["choices"][0]["message"]["content"]
- [Phase 05]: FREELLMAPI_MODEL default changes from "llama3" to "auto" (freellmapi model routing alias)
- [Phase 05]: Provider API keys (Gemini, OpenRouter) configured via freellmapi web dashboard at localhost:3001 — not env vars passed to containers
- [Phase ?]: Use pytest.mark.skipif for smoke tests — evaluates at collection time with informative reason for CI
- [Phase 05]: llm_router uses OpenAI /v1/chat/completions format with Bearer auth and choices[0].message.content parsing — switched from Ollama /api/chat
- [Phase 06 planned]: HermesLLMClient is a thin async wrapper over openai.AsyncOpenAI; startup self-test logs success/failure and never raises on connection error
- [Phase ?]: Reload hermes.llm_client before patching AsyncOpenAI in env-var test — reload re-executes module-level os.getenv, then patch intercepts instantiation on fresh module
- [v1.3 planned]: mcp-atlassian uses per-request credentials (not hardcoded env vars) — critical for multi-project support; each call passes jira_url/jira_email/jira_token at the transport level
- [v1.3 planned]: Hermes gains a FastAPI HTTP server for /jira/* endpoints (currently asyncio event loop only); hermes becomes both an MCP client and an HTTP server the backend calls
- [v1.3 planned]: Backend call sites to migrate — describe_pipeline.py (sprint backlog), webhook.py (add_comment x2), approval_detector.py (update_description + add_comment), assign_pipeline.py (lookup_user + assign_issue)
- [v1.4 roadmap]: complexity_classifier.py is a new isolated module — no DB or Jira side effects; independently unit-testable
- [v1.4 roadmap]: drawio-skill (Agents365-ai/drawio-skill) is an AI agent instruction file, not a Python library; integration approach is to enhance existing in-memory mxGraph XML builder in drawio_service.py — no subprocess call, no new deps
- [v1.4 roadmap]: Diagram embedding uses mxGraph XML in <pre class="drawio-xml"> block plus diagrams.net viewer URL — plugin-agnostic; no draw.io desktop binary needed
- [v1.4 roadmap]: Confluence client gets find-or-update logic (search by title "Architecture: {issue_key}" before create) to prevent duplicate pages
- [v1.4 roadmap]: PipelineState.draft_content must be flat human-readable text (summary + Confluence link), never a JSON blob — approval_detector.py contract
- [v1.4 roadmap]: Webhook idempotency guard in Phase 13: if active PipelineState for same ticket at stage="architecture" exists (status != "failed"), return 200 without re-triggering
- [Phase ?]: classify stage is HEAVY_STAGES not KNOWN_STAGES — internal pipeline stage, not user-triggerable (Phase 10)
- [Phase ?]: complexity_classifier.py: zero Jira/hermes/crypto imports enforced — isolation for testability (Phase 10)
- [Phase ?]: Malformed LLM JSON in classify defaults to ('small', 'Classification unavailable') — safe fallback (Phase 10)
- [Phase ?]: Typed shapes use keyword matching (case-insensitive) in _component_style — matches LLM-generated component name patterns without schema changes
- [Phase ?]: validate_xml catches ET.ParseError plus bare Exception — returns False, never raises (T-11-03 mitigation)
- [Phase 12-structured-confluence-publishing]: Confluence page title standardized to 'Architecture: {issue_key}' for consistent find_page lookups — Enables find-or-update idempotency: same title used by find_page CQL search before create/update
- [Phase ?]: Single-pass complexity-aware architecture pipeline replaces multi-option flow (ARCHGEN-01, ARCHINT-03)
- [Phase ?]: PipelineState.status lifecycle: running to complete, not awaiting_approval
- [Phase 13-02]: Webhook idempotency guard: status != 'failed' allows retry; active runs (running/complete) block duplicate task scheduling
- [Phase 13-02]: Webhook creates PipelineState(status=running) before asyncio.create_task; pipeline re-uses existing row
- [Phase 13-02]: Architecture approval path removed from approval_detector — dead code after Plan 01 changed lifecycle to running→complete
- [v1.5 roadmap]: KNOWN_STAGES whitelist in mention_parser.py replaced by LLM intent classifier — free-text @jarvis mentions supported without hardcoded keyword enumeration (Phase 14)
- [v1.5 roadmap]: Unrecognized intents post a helpful Jira comment listing valid commands rather than silently dropping the event (INTENT-02, Phase 14)
- [v1.5 roadmap]: github_repo stored encrypted alongside existing project credentials; displayed in dashboard (GITHUBCFG-01, GITHUBCFG-02, Phase 15)
- [v1.5 roadmap]: Dev pipeline branch name convention is jarvis/issue-{key}; PR opened against main via GitHub API with stored token (DEVPIPE-04, Phase 15)
- [v1.5 roadmap]: DEVPIPE-01 reads Confluence architecture URL from ticket comment history (posted by architecture pipeline); fetches page via Hermes Confluence MCP client (Phase 16)
- [v1.5 roadmap]: PRMERGE-01 locates PR by branch pattern jarvis/issue-{key} or PR title match; merges to main; posts merge commit SHA to Jira comment (Phase 17)
- [v1.6 roadmap]: Codebase scan uses git clone + directory tree walk + targeted file reads — no LLM; output is a structured markdown file committed directly to main as .hermes/codebase.md (Phase 18)
- [v1.6 roadmap]: Scan triggered automatically on project onboarding when github_repo is saved — no separate user action required (SCAN-01, Phase 18)
- [v1.6 roadmap]: Snapshot refresh hooks into merge_pipeline.py post-merge path (SNAPSHOT-01, Phase 19); read path degrades gracefully when file absent (SNAPSHOT-02, Phase 19)
- [v1.6 roadmap]: describe_pipeline.py and architecture_pipeline.py both read .hermes/codebase.md via GitHub API before their LLM calls; during dev pipeline the local clone path can also be used (Phases 20-21)
- [v1.6 roadmap]: Architecture pipeline passes codebase context to both the complexity classifier call and the generation call in a single read operation (ARCHCTX-01, Phase 21)
- [Phase 21-01]: architecture_pipeline.run() fetches codebase snapshot exactly once (single await call site) and threads it through as a parameter to classify_complexity()/_run_complex()/_run_simple() — get_codebase_snapshot is never called inside the per-complexity branches
- [Phase ?]: RuntimeError message format uses only owner/repo/status_code — github_token never interpolated (T-18-01 compliance, 18-04)
- [Phase 19-snapshot-refresh-read-fallback]: Post-merge re-scan hook uses isolated try/except; scan failure never flips state_row.status or modifies Jira comment body (T-19-02 compliance, SNAPSHOT-01)
- [Phase ?]: Phase 19-02 decision

### Pending Todos

None — v1.6 roadmap created; ready to begin Phase 18 planning.

### Quick Tasks Completed

| ID | Description | Date |
|----|--------------|------|
| 260619-hlp | Confluence MCP migration (replace direct REST ConfluenceClient with MCP tool call) | 2026-06-19 |
| 260619-o0v | Auto-trigger description generation on Story creation (jira:issue_created webhook); replace keyword-based approval detection with `@jarvis approve story description` / `@jarvis approve architecture` mentions; remove `@jarvis describe` comment trigger | 2026-06-19 |
| 260622-hye | Enhance dev pipeline: inject relevant file contents into codegen prompt (read_relevant_files); add Claude Code CLI executor used when CLAUDE_API_KEY set, falls back to freellmapi otherwise | 2026-06-22 |

### Blockers/Concerns

None.

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| v1.4.x | Hybrid rule-based pre-filter before LLM classification (keyword/component-count guardrail) | Deferred | v1.4 planning |
| v1.4.x | Override trigger @jarvis architecture force-complex / force-simple | Deferred | v1.4 planning |
| v1.5 | Auto-chain architecture generation after @jarvis describe approval | Deferred | v1.4 planning |
| v1.5 | Confluence MCP migration (replace direct REST ConfluenceClient with MCP tool call) | **Done** (quick task 260619-hlp, 2026-06-19) | v1.4 planning |
| v1.6.x | On-demand refresh trigger (@jarvis refresh codebase) | Deferred | v1.6 planning |
| v1.6.x | Diff-based incremental scan (re-scan only changed files) | Deferred | v1.6 planning |
| v2+ | Codebase embedding / vector search | Deferred | v1.6 planning |

## Session Continuity

Last session: 2026-06-22T13:38:17.694Z
Stopped at: Quick task 260622-hye closed out (SUMMARY.md + STATE.md row written); session resumed
Resume file: None
Next action: Run `/gsd-complete-milestone` to archive v1.6 and prepare next milestone.
