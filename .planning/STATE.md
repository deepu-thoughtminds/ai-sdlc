---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: SonarQube QA Integration
current_phase: 31
status: verifying
stopped_at: Phase 30 Plan 01 complete — sonar-scanner step integrated in QA pipeline
last_updated: "2026-06-27T11:23:33.159Z"
last_activity: 2026-06-27
last_activity_desc: Phase 31 complete
progress:
  total_phases: 9
  completed_phases: 6
  total_plans: 11
  completed_plans: 10
  percent: 67
current_phase_name: confluence-report-section
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-27)

**Core value:** Team members trigger AI-powered SDLC automation directly from Jira comment history, with every output linked back to the originating ticket.
**Current focus:** v2.0 milestone complete — SonarQube QA Integration shipped

## Current Position

Phase: 31
Plan: Not started
Status: Phase complete — ready for verification
Last activity: 2026-06-27 — Phase 31 complete

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
| v1.7 agentic-codegen | 1 (Phase 22) | 1 | Complete | 2026-06-23 |
| v1.8 autonomous-qa-stage | 4 (Phases 23-26) | 5 | Complete | 2026-06-24 |
| v1.8 autonomous-qa-stage | 4 (Phases 23-26) | TBD | In Progress | — |

## Performance Metrics

**Velocity:**

- Total plans completed: 34
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
| 23 | 2 | - | - |
| 24 | 1 | - | - |
| 27 | 1 | - | - |
| 28 | 1 | - | - |
| 29 | 2 | - | - |
| 31 | 1 | - | - |

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
| Phase 22 P01 | 25m | 3 tasks | 6 files |
| Phase 23 P23-01 | 2min | 3 tasks | 4 files |
| Phase 23 P23-02 | 15 | 2 tasks | 4 files |
| Phase 28 P01 | 12min | 3 tasks | 2 files |
| Phase 30 P01 | 2 | 2 tasks | 4 files |
| Phase 31 P01 | 58 | 3 tasks | 5 files |

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
- [Phase 22]: Used ghcr.io/berriai/litellm:main-latest per plan (resolves >=1.82.9, past 1.82.7/1.82.8 malware incident)
- [Phase 22]: Left claude_code_executor.py and code_generator.py as unused dead code per plan instructions (no other module imports them from dev_pipeline)
- [v1.8 roadmap]: QA test execution uses subprocess.run() inside an ephemeral sibling container (docker>=7.1.0 Python SDK); never reuses dev/merge pipeline workspace; hard 120s per-command timeout (TESTEXEC-01, TESTEXEC-02, Phase 23)
- [v1.8 roadmap]: QA sandbox image based on mcr.microsoft.com/playwright:v1.49.0-noble with ruff/mypy/bandit/semgrep pre-installed; Playwright package version pinned to match image tag — version mismatch is most common Playwright-in-Docker failure mode (Phase 23)
- [v1.8 roadmap]: Auto-fix commits use pr_creator.py branch jarvis/qa-fix-{issue_key}; never pushed directly to main — autonomy boundary matches dev pipeline (AUTOFIX-03, Phase 25)
- [v1.8 roadmap]: Auto-fix loop terminates early on same-error repeat (non-progress detection) as well as 3-attempt cap; PipelineState.qa_attempt persists count across restarts (AUTOFIX-02, AUTOFIX-04, Phase 25)
- [v1.8 roadmap]: Playwright E2E generation gated on detecting playwright.config.* in cloned repo; skip note posted to Jira when absent — no scaffolding new E2E infra in v1.8 (TESTGEN-03, Phase 26)
- [v1.8 roadmap]: Both trigger paths (auto-chain from merge_pipeline.py + @jarvis run qa comment) share a single scheduling helper with one idempotency check — mirrors existing architecture/merge_pr pattern (QATRIG-01, QATRIG-02, QATRIG-03, Phase 26)
- [Phase ?]: qa_pipeline.run() pre-binds jira_token/jira_email before try block to avoid NameError in failure-comment path if decrypt_credential raises early
- [Phase ?]: [Phase 28-01]: managed_app_container replaces PLAYWRIGHT_BASE_URL env-var in qa_pipeline Step 4d — health-check gated URL
- [Phase ?]: [Phase 28-01]: compose_network factored to single call before outer try block in qa_pipeline.run()
- [Phase ?]: [Phase 30-01]: sonar-scanner step at Step 5.2 in qa_pipeline.run() after run_static_analysis; isolated sonar_scanner.py module, all failure paths return TestResult, never raises
- [Phase ?]: SonarMetrics dataclass transports quality gate metrics from SonarQube API to Confluence renderer
- [Phase ?]: TYPE_CHECKING guard in confluence_client.py for SonarMetrics import avoids circular import at runtime
- [Phase ?]: fetch_sonar_metrics never raises — exceptions return None so QA pipeline is never blocked by metrics fetch failure

### Pending Todos

None — v1.8 roadmap created (Phases 23–26); ready to begin Phase 23 planning.

### Quick Tasks Completed

| ID | Description | Date |
|----|--------------|------|
| 260619-hlp | Confluence MCP migration (replace direct REST ConfluenceClient with MCP tool call) | 2026-06-19 |
| 260619-o0v | Auto-trigger description generation on Story creation (jira:issue_created webhook); replace keyword-based approval detection with `@jarvis approve story description` / `@jarvis approve architecture` mentions; remove `@jarvis describe` comment trigger | 2026-06-19 |
| 260622-hye | Enhance dev pipeline: inject relevant file contents into codegen prompt (read_relevant_files); add Claude Code CLI executor used when CLAUDE_API_KEY set, falls back to freellmapi otherwise | 2026-06-22 |
| 260622-p0f | Replace graphify indexing with codebase-memory-mcp in backend container; remove /graphify + /gsd-graphify from executor prompt; use codebase-memory-mcp index + /gsd-quick | 2026-06-22 |
| 260622-fix-executor-prompt | Fix executor prompt to enforce targeted edits via get_code_snippet; remove /gsd-quick; revert LoginPage.tsx in test-blog broken by SCRUM-70 PR | 2026-06-22 |
| 260625-6tz | scripts/seed_dev_data.py (dump/seed) to restore backend test project + freellmapi routing settings after `docker compose down -v` wipes volumes | 2026-06-25 |
| 20260626-playwright-python-e2e | Python Playwright evaluation via Claude Code CLI in QA pipeline: generate pytest-playwright scripts, run in Docker, include results in Jira comment + Confluence QA report | 2026-06-26 |
| 260625-7z1 | Fix qa_pipeline.py to dispatch .test.ts/.test.tsx/.spec.ts/.spec.tsx files to `npm ci && npm test` inside qa-sandbox instead of hardcoding pytest; .py files unchanged | 2026-06-25 |

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
| v1.8+ | Intermediate "QA in progress, attempt N of M" Jira comment updates during auto-fix loop | Deferred | v1.8 planning |
| v1.8+ | Mixed-stack/monorepo toolchain detection refinement | Deferred | v1.8 planning |
| v2+ | Scaffolding new Playwright E2E infra for repos that have none | Deferred | v1.8 planning |
| v2+ | Auto-merge on QA pass | Deferred | v1.8 planning |
| v1.9+ | Workspace reuse optimization between dev/merge/QA stages | Deferred | v1.8 planning |
| debug | scrum54-dev-pipeline-missing-arch-url (dev_pipeline.py fails to look up architecture URL published by architecture_pipeline) | Acknowledged — awaiting_human_verify | v1.6 close (2026-06-22) |
| uat_gap | Phase 17 (17-UAT.md) — 3 scenarios not yet tested | Acknowledged — testing | v1.6 close (2026-06-22) |
| verification_gap | Phase 15 (15-VERIFICATION.md) — gaps found | Acknowledged — gaps_found | v1.6 close (2026-06-22) |
| quick_task | fix-mcp-client-headers (20260619) | Acknowledged — missing | v1.6 close (2026-06-22) |
| quick_task | 260618-lbw-fix-onboard-project-failing-with-failed- | Acknowledged — missing | v1.6 close (2026-06-22) |
| quick_task | 260618-n0u-fix-webhook-422-for-real-jira-automation | Acknowledged — unknown | v1.6 close (2026-06-22) |
| quick_task | 260619-hlp-route-confluence-publishing-through-mcp- | Acknowledged — unknown | v1.6 close (2026-06-22) |
| quick_task | 260619-o0v-change-description-generation-to-auto-tr | Acknowledged — unknown | v1.6 close (2026-06-22) |

## Session Continuity

Last session: 2026-06-27
Stopped at: Phase 31 complete — v2.0 milestone complete, all 9 phases done
Resume file: None

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
