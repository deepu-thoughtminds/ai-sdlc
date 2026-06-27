# Roadmap: AI-SDLC Jira

## Overview

Four phases deliver the complete v1 platform. Phase 1 builds the event-driven backbone (Docker Compose + webhook receiver + mention parser + LLM router) that every later phase depends on. Phase 2 adds the web dashboard for project onboarding and encrypted credential management. Phase 3 wires the first end-to-end SDLC pipeline: description elaboration from codebase context through to Jira field update, plus the assignment trigger that hands a ticket to an architect. Phase 4 completes the v1 scope with the architecture pipeline — diagram generation, Confluence publishing, approval loop, and the remaining assignment triggers that close the hand-off chain.

Phase 5 (milestone v1.1) replaces the Ollama stub in the LLM layer with the real freellmapi service (tashfeenahmed/freellmapi), wiring Docker Compose, the LLM router, and environment configuration to deliver actual LLM responses through the full pipeline.

Phase 6 (milestone v1.2) gives the Hermes agent container its own dedicated LLM client — a thin async wrapper over the OpenAI SDK pointed at freellmapi — so all Hermes orchestration calls go through a typed, testable interface instead of raw HTTP.

Phases 7-9 (milestone v1.3) replace all direct Jira REST calls in the platform with MCP tool calls routed through mcp-atlassian. Phase 7 stands up the mcp-atlassian Docker service with per-request credential support and installs the MCP SDK in the Hermes container. Phase 8 adds the HermesMCPClient class with typed tool wrappers and the four Hermes internal Jira HTTP endpoints the backend will call. Phase 9 migrates every backend call site from JiraClient to the hermes Jira API and removes jira_client.py entirely.

Phases 10-13 (milestone v1.4) replace the multi-option architecture flow with a single complexity-aware pipeline. Phase 10 introduces an isolated complexity classifier module. Phase 11 enhances the diagram service with validated mxGraph XML output and a diagrams.net viewer URL. Phase 12 updates the Confluence client with two structured HTML templates and idempotent page management. Phase 13 rewires the full pipeline in architecture_pipeline.py, adds a webhook idempotency guard, and removes the old multi-option approval flow.

Phases 14-17 (milestone v1.5) deliver the GitHub developer pipeline and replace the hardcoded mention-parser keyword whitelist with an LLM-based intent router. Phase 14 replaces KNOWN_STAGES with a free-text LLM intent classifier. Phase 15 adds the GitHub repo field to the project model and web app and implements the clone → code-generate → PR creation foundation. Phase 16 wires the end-to-end `@jarvis start coding` trigger that reads the Confluence architecture from comment history and posts the resulting PR link back to Jira. Phase 17 delivers the `@jarvis merge pr` trigger that merges the open PR via GitHub API and updates the Jira story status.

Phases 18-21 (milestone v1.6) give every pipeline stage accurate, real codebase context. Phase 18 delivers the codebase scan service: on project onboarding the agent clones the repo, walks the directory tree with targeted file reads, and commits a structured `.hermes/codebase.md` summary to main — no LLM involved. Phase 19 hooks the scan into the post-merge lifecycle: after a successful `@jarvis merge pr` the snapshot is refreshed automatically, and the read path degrades gracefully when the file does not yet exist. Phase 20 wires codebase context into the describe pipeline so story elaborations reference real module names and file paths. Phase 21 wires the same context into both the complexity classifier and architecture generation calls so architecture writeups reference actual components and integration points instead of invented structure.

Phases 23-26 (milestone v1.8) add the Autonomous QA Stage. Phase 23 builds the sandboxed execution foundation — `test_executor.py`, a dedicated `qa-sandbox` Docker image, toolchain auto-detection, and `PipelineState.qa_attempt` tracking — establishing the right architectural boundary (LLM generates files; orchestrator runs them) before any test generation exists. Phase 24 adds LLM-driven unit test generation via freellmapi, reusing the `### FILE:` output convention, executing generated tests in the sandbox, and posting the first QA result to Jira. Phase 25 implements the bounded auto-fix loop: up to 3 freellmapi-driven fix attempts with non-progress detection, context-refreshed prompts per iteration, and fix commits raised as PRs via `pr_creator.py` — never pushed directly to main. Phase 26 wires everything together: Playwright E2E test generation with graceful skip when no `playwright.config.*` exists, auto-chain from `merge_pipeline.py` post-merge, `@jarvis run qa` comment trigger, and a shared idempotency guard covering both trigger paths.

Phases 27-28 (milestone v1.9) add Playwright E2E Live Testing. Phase 27 builds the new `app_container.py` service that detects the target app's serve command, spins up an ephemeral Node.js container on the compose network, polls until HTTP 200, and guarantees teardown. Phase 28 wires the live container URL into `qa_pipeline.py` as the authoritative `BASE_URL` for the Playwright generator, gates generation on the health-check result, handles graceful skip when the app cannot be served, and threads the live URL through to test execution and the Confluence/Jira QA report.

Phases 29-31 (milestone v2.0) embed SonarQube static analysis into the QA pipeline. Phase 29 adds SonarQube Community Edition as a persistent Docker Compose service, waits for it to reach UP status, and bootstraps an admin token on first start. Phase 30 adds a sonar-scanner step to the QA pipeline (after static analysis, before Playwright E2E), using a per-repo project key and polling the CE task API until analysis completes — the step never hard-fails the pipeline. Phase 31 appends a SonarQube section to the Confluence QA page with quality gate status, bug/vulnerability/code-smell counts, coverage, duplications, and a deep link to the dashboard; when the scan is unavailable the section shows a graceful fallback note.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - Docker Compose services, Jira webhook receiver, mention parser, and LLM router
- [x] **Phase 2: Web App** - Project onboarding dashboard with encrypted credential storage and ticket status view (completed 2026-06-18)
- [x] **Phase 3: Description Elaboration** - Full description pipeline from graphify context through user approval to Jira field update, plus BU-to-architect assignment trigger (completed 2026-06-18)
- [x] **Phase 4: Architecture Pipeline** - Architecture options, drawio diagrams, Confluence publishing, approval loop, and remaining assignment triggers (completed 2026-06-18)
- [x] **Phase 5: freellmapi Integration** - Replace Ollama stub with real freellmapi service: git submodule, Docker Compose wiring, OpenAI-format LLM router, and smoke-test verified real responses (completed 2026-06-18)
- [x] **Phase 6: Hermes LLM Client** - Typed async LLM client in the Hermes container, wired to freellmapi, with startup self-test and full unit test coverage (completed 2026-06-18)
- [ ] **Phase 7: MCP Infrastructure** - mcp-atlassian Docker service with per-request credential support and MCP SDK installed in the Hermes container
- [ ] **Phase 8: Hermes MCP Client + Internal API** - HermesMCPClient with all 5 typed tool methods and 4 internal Jira HTTP endpoints that the backend will call
- [ ] **Phase 9: Backend Migration** - All 5 JiraClient call sites in the backend replaced with hermes Jira API calls; jira_client.py removed
- [x] **Phase 10: Complexity Classifier** - New complexity_classifier.py module with structured LLM classification call, explicit rubric, and boundary-focused unit tests (completed 2026-06-19)
- [x] **Phase 11: Enhanced Diagram Service** - drawio_service.py enhanced with validated mxGraph XML output, directional edges, typed-component placement, and diagrams.net viewer URL (completed 2026-06-19)
- [ ] **Phase 12: Structured Confluence Publishing** - confluence_client.py updated with two HTML templates (text-only and diagram+components), HTML-escaped content, idempotent find-or-update page logic, and graceful degradation
- [ ] **Phase 13: Pipeline Orchestration & Integration** - architecture_pipeline.py rewritten to wire classifier → diagram → Confluence → Jira comment; webhook idempotency guard added; old multi-option flow removed
- [x] **Phase 14: LLM Intent Router** - Replace KNOWN_STAGES whitelist in mention_parser.py with LLM-based free-text intent extraction; unrecognized intents post a helpful Jira comment listing valid commands (completed 2026-06-20)
- [x] **Phase 15: GitHub Config & Dev Pipeline Foundation** - Add github_repo field to project DB and web app form; implement clone → code-generate → PR creation pipeline modules (completed 2026-06-20)
- [x] **Phase 16: Dev Pipeline Integration** - Wire @jarvis start coding end-to-end: read Confluence architecture from comment history, run dev pipeline, post PR link to Jira (completed 2026-06-21)
- [x] **Phase 17: PR Merge Pipeline** - Wire @jarvis merge pr trigger: find open PR by branch pattern, merge via GitHub API, update Jira story status, post merge commit to Jira comment (completed 2026-06-21)
- [x] **Phase 18: Codebase Scan Service** - On project onboarding, clone the repo and walk the directory tree with targeted file reads; commit structured `.hermes/codebase.md` to main branch (completed 2026-06-21)
- [x] **Phase 19: Snapshot Refresh & Read Fallback** - After successful PR merge, re-run codebase scan and push updated snapshot; read path degrades gracefully when snapshot does not exist (completed 2026-06-22)
- [x] **Phase 20: Describe Pipeline Context** - describe_pipeline.py reads `.hermes/codebase.md` via GitHub API before LLM call; generated story elaborations reference real module names and file paths (completed 2026-06-22)
- [x] **Phase 21: Architecture Pipeline Context** - architecture_pipeline.py reads `.hermes/codebase.md` and includes it in the complexity classifier and architecture generation LLM calls; outputs reference actual components and integration points (completed 2026-06-22)

## Milestone v1.7: Agentic Codegen via LiteLLM + Claude Agent SDK

- [x] **Phase 22: Agentic Codegen** - Replace the freellmapi text-completion codegen path with a fully agentic coding loop: Claude Agent SDK → LiteLLM proxy (Anthropic→OpenAI translation) → freellmapi → free LLMs. Enables the dev pipeline to handle any complexity of story — from single-line text changes to multi-file architectural features — without Anthropic API costs. (completed 2026-06-23)

## Milestone v1.8: Autonomous QA Stage

- [x] **Phase 23: QA Foundation & Sandbox Execution** - test_executor.py (toolchain detection + subprocess execution with resource limits), qa-sandbox Docker image, qa_pipeline.py skeleton, PipelineState.qa_attempt field, static analysis execution without LLM (completed 2026-06-23)
- [x] **Phase 24: Test Generation** - test_generator.py generates pytest unit tests via freellmapi using cloned repo context + codebase.md, writes tests to workspace, executes via sandbox, posts first QA result to Jira (completed 2026-06-24)
- [x] **Phase 25: Bounded Auto-Fix Loop** - auto_fix_loop.py with 3-attempt iteration cap, non-progress detection (same-error termination), incremental context refresh per iteration, fix commits raised as PRs via pr_creator.py (completed 2026-06-24)
- [x] **Phase 26: E2E + Trigger Wiring** - Playwright E2E test generation with graceful skip when no playwright.config.* exists, auto-chain from merge_pipeline.py, @jarvis run qa comment trigger, shared idempotency guard for both trigger paths (completed 2026-06-24)

## Milestone v1.9: Playwright E2E Live Testing

- [x] **Phase 27: App Container Service** - app_container.py: detect serve command, ephemeral container on compose network, health-check, teardown (completed 2026-06-26) — [archived in v1.9]
- [x] **Phase 28: QA Pipeline Integration** - wire live container URL as BASE_URL, gate E2E on health-check, graceful skip, live URL in reports (completed 2026-06-26) — [archived in v1.9]

## Phase Details

### Phase 1: Foundation

**Goal**: All services run together and Jira comment events reach the correct pipeline stage handler
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04
**Success Criteria** (what must be TRUE):

  1. `docker compose up` starts Hermes agent, freellmapi, FastAPI backend, and Next.js frontend with no manual steps
  2. A Jira comment webhook POST reaches the FastAPI endpoint and is acknowledged with a 200 response
  3. A comment containing `@hermes describe` is parsed to identify the mention target and pipeline stage; an unrecognised comment is silently ignored
  4. A request classified as heavy (architecture, code gen) is routed to freellmapi; a lightweight orchestration request uses the configured main model

**Plans**: 2 plans
Plans:
**Wave 1**

- [x] 01-01-PLAN.md — Docker Compose service definitions, Dockerfiles, and inter-container networking (INFRA-01)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — FastAPI webhook endpoint, mention parser, and LLM router (INFRA-02, INFRA-03, INFRA-04)

### Phase 2: Web App

**Goal**: Team members can onboard projects and view per-ticket pipeline status without touching config files
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: WEBAPP-01, WEBAPP-02, WEBAPP-03, WEBAPP-04
**Success Criteria** (what must be TRUE):

  1. User fills in a form with Jira URL, GitHub token, Confluence URL, and project key, submits it, and the project appears in the dashboard list
  2. Dashboard lists every onboarded project and shows the current pipeline stage for each active ticket
  3. Stored credentials are encrypted at rest; plaintext tokens are never returned by any API response or written to logs
  4. User can see which SDLC stage (description, architecture, dev, QA) each active ticket is currently at

**Plans**: 3 plans

Plans:

- [x] 13-01-PLAN.md — Rewrite architecture_pipeline.py: single-pass complexity-aware flow (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-03)
- [x] 13-02-PLAN.md — Webhook idempotency guard + remove architecture approval from approval_detector.py (ARCHINT-01, ARCHINT-02, ARCHINT-03)
- [ ] 13-03-PLAN.md — Replace architecture pipeline tests + add idempotency test to test_webhook.py (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-02)

**UI hint**: yes

Plans:

- [x] 02-01: FastAPI credential storage API with encryption and Next.js project onboarding form
- [x] 02-02: Dashboard views for project list and per-ticket pipeline stage status

### Phase 3: Description Elaboration

**Goal**: A business user can mention the agent in a Jira comment to get an elaborated feature description reviewed and applied to the ticket, and can then assign the ticket to an architect
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: DESC-01, DESC-02, DESC-03, DESC-04, ASGN-01
**Success Criteria** (what must be TRUE):

  1. Agent reads the gsd-graphify knowledge graph for the project and incorporates relevant codebase patterns into the generated description
  2. Agent fetches the current sprint backlog from Jira and uses it as context when generating the description
  3. Elaborated description appears as a new comment on the Jira ticket within a reasonable time of the trigger mention
  4. User types an approval reply in the comment thread; agent detects it and updates the epic/story description field via Jira MCP
  5. Business user mentions `@hermes assign @architect-name` in a comment and the ticket is re-assigned to that team member in Jira

**Plans**: 3 plans

Plans:

- [ ] 13-01-PLAN.md — Rewrite architecture_pipeline.py: single-pass complexity-aware flow (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-03)
- [x] 13-02-PLAN.md — Webhook idempotency guard + remove architecture approval from approval_detector.py (ARCHINT-01, ARCHINT-02, ARCHINT-03)
- [ ] 13-03-PLAN.md — Replace architecture pipeline tests + add idempotency test to test_webhook.py (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-02)

Plans:

- [x] 03-01: graphify integration, sprint backlog fetch, and description generation via freellmapi
- [x] 03-02: Comment posting, approval detection loop, Jira field update, and assignment trigger

### Phase 4: Architecture Pipeline

**Goal**: An architect can trigger the agent to produce architecture options with drawio diagrams published to Confluence, approve a choice, and hand the ticket off to a developer; remaining assignment triggers (arch-to-dev, dev-to-QA) are also wired
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: ARCH-01, ARCH-02, ARCH-03, ARCH-04, ASGN-02, ASGN-03
**Success Criteria** (what must be TRUE):

  1. Architect mentions the agent and receives multiple architecture options with trade-off analysis posted to the Jira comment
  2. Each architecture option includes at least one drawio diagram generated by the drawio skill
  3. Architecture document (diagrams + analysis) is published to a Confluence page and the page URL is posted back to the Jira comment
  4. Architect posts an approval comment; agent detects it and re-assigns the ticket to the named developer in Jira
  5. Architect can mention `@hermes assign @developer-name` to assign a ticket to a developer; developer can mention `@hermes assign @qa-name` to assign a merged-PR ticket to QA

**Plans**: 2 plans

Plans:

**Wave 1**

- [x] 04-01-PLAN.md — drawio_service + confluence_client + architecture_pipeline (generation, diagram assembly, Confluence publishing) (ARCH-01, ARCH-02, ARCH-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 04-02-PLAN.md — architecture approval detection, webhook routing for architecture stage, ASGN-02/ASGN-03 confirmation (ARCH-04, ASGN-02, ASGN-03)

### Phase 5: freellmapi Integration

**Goal**: The freellmapi service runs from source as a git submodule, the LLM router speaks the OpenAI-compatible API it exposes, and a real LLM response flows end-to-end through the `@hermes describe` pipeline
**Mode:** mvp
**Depends on**: Phase 4
**Milestone**: v1.1 — freellmapi
**Requirements**: FLLM-01, FLLM-02, FLLM-03, FLLM-04, FLLM-05, FLLM-06, FLLM-07
**Success Criteria** (what must be TRUE):

  1. `git submodule update --init` pulls the freellmapi source and `docker compose build` succeeds without manual steps
  2. `docker compose up` starts freellmapi on port 3001 with a named volume persisting the encrypted key store across restarts
  3. A heavy-stage request from `llm_router.py` reaches freellmapi at `/v1/chat/completions` with a Bearer token and the response text is extracted from `choices[0].message.content`
  4. `.env.example` documents FREELLMAPI_ENCRYPTION_KEY, FREELLMAPI_API_KEY, GEMINI_API_KEY, and OPENROUTER_API_KEY with generation instructions; FREELLMAPI_BASE_URL points to `http://freellmapi:3001`
  5. All 88 existing tests pass after mock shapes are updated to OpenAI-format responses
  6. A smoke test (skipped when FREELLMAPI_API_KEY is unset) sends a real `/v1/chat/completions` request and receives a non-stub LLM response

**Plans**: 2 plans

Plans:

**Wave 1**

- [x] 05-01-PLAN.md — git submodule add freellmapi, update docker-compose.yml (port 3001, build from submodule, named volume, env vars), update .env.example (FLLM-01, FLLM-02, FLLM-04, FLLM-05)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 05-02-PLAN.md — update llm_router.py to OpenAI /v1/chat/completions format with Bearer auth, update test_llm_router.py mocks, add smoke test (FLLM-03, FLLM-06, FLLM-07)

### Phase 6: Hermes LLM Client

**Goal**: The Hermes agent container has a typed async LLM client backed by freellmapi, with a safe startup self-test and full unit test coverage, so all Hermes orchestration calls go through a testable interface rather than raw HTTP
**Mode:** mvp
**Depends on**: Phase 5
**Milestone**: v1.2 — hermes-freellmapi
**Requirements**: HERMES-01, HERMES-02, HERMES-03, HERMES-04, HERMES-05, HERMES-06
**Success Criteria** (what must be TRUE):

  1. `docker compose build hermes` succeeds with the `openai` Python SDK installed (visible in the built image's `pip list`)
  2. `hermes/llm_client.py` exports `HermesLLMClient` with an async `chat(messages, model="auto") -> str` method
  3. `docker compose up hermes` logs either "LLM self-test passed" or "LLM self-test failed (freellmapi unavailable)" and the container stays running in both cases
  4. Unit tests for `HermesLLMClient` pass without a live API key — all OpenAI SDK calls are mocked

**Plans**: 2 plans

Plans:

**Wave 1**

- [x] 06-01-PLAN.md — Add `openai>=1.0` to hermes/requirements.txt, implement hermes/llm_client.py with async HermesLLMClient, wire FREELLMAPI_BASE_URL and FREELLMAPI_API_KEY env vars into hermes container in docker-compose.yml (HERMES-01, HERMES-02, HERMES-03, HERMES-04)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 06-02-PLAN.md — Startup self-test in hermes/__main__.py that calls freellmapi with a ping prompt and logs success/failure without crashing; unit tests for HermesLLMClient with mocked OpenAI responses (HERMES-05, HERMES-06)

### Phase 7: MCP Infrastructure

**Goal**: The mcp-atlassian MCP server runs as a Docker service reachable by Hermes, supports per-request Jira credentials for multi-project use, and the Hermes container has the Python MCP SDK installed
**Depends on**: Phase 6
**Milestone**: v1.3 — hermes-mcp-agent
**Requirements**: MCPINFRA-01, MCPINFRA-02, MCPINFRA-03
**Success Criteria** (what must be TRUE):

  1. `docker compose up` starts an `mcp-atlassian` container from the sooperset/mcp-atlassian image and it is reachable by Hermes on ai-sdlc-net without manual network setup
  2. A Jira operation request carrying project-specific `jira_url`, `jira_email`, and `jira_token` values is processed using those credentials — not hardcoded env vars — confirming multi-user credential support
  3. `docker compose build hermes` succeeds and the `mcp` Python package (and HTTP/SSE transport dependencies) are present in the built image

**Plans**: 1 plan

Plans:

**Wave 1**

- [ ] 07-01-PLAN.md — mcp-atlassian Docker service, per-request credential config, MCP SDK in hermes image, infrastructure smoke tests (MCPINFRA-01, MCPINFRA-02, MCPINFRA-03)

### Phase 8: Hermes MCP Client + Internal API

**Goal**: Hermes exposes a typed async client over mcp-atlassian and four internal HTTP endpoints so the FastAPI backend can perform every Jira operation through Hermes rather than calling Jira directly
**Depends on**: Phase 7
**Milestone**: v1.3 — hermes-mcp-agent
**Requirements**: MCPCLIENT-01, MCPCLIENT-02, MCPCLIENT-03, MCPCLIENT-04, MCPCLIENT-05, MCPCLIENT-06, MCPAPI-01, MCPAPI-02, MCPAPI-03, MCPAPI-04
**Success Criteria** (what must be TRUE):

  1. `hermes/mcp_client.py` exports `HermesMCPClient` and each of the five typed methods (`add_comment`, `update_description`, `get_sprint_issues`, `lookup_user`, `assign_issue`) can be called with per-request credentials and returns the documented type
  2. `POST /jira/comment` called with valid credentials and an issue key returns a JSON body containing `comment_id`
  3. `PUT /jira/description` called with valid credentials updates the issue description and returns an empty JSON body
  4. `POST /jira/sprint-backlog` returns a JSON array of `{key, summary, issue_type}` objects for the requested project
  5. `POST /jira/assign` accepts a display name, resolves it to a Jira `accountId` via user lookup, assigns the issue, and returns `{account_id}`

**Plans**:

- 08-01: HermesMCPClient typed async wrappers (Wave 1, complete)
- 08-02: Hermes FastAPI server /jira/* endpoints + uvicorn boot + port 8001 (Wave 2, complete)

### Phase 9: Backend Migration

**Goal**: Every Jira operation in the backend goes through the Hermes internal API; jira_client.py no longer exists and no backend module imports JiraClient
**Depends on**: Phase 8
**Milestone**: v1.3 — hermes-mcp-agent
**Requirements**: MCPMIG-01, MCPMIG-02, MCPMIG-03, MCPMIG-04, MCPMIG-05
**Success Criteria** (what must be TRUE):

  1. `describe_pipeline.py` fetches the sprint backlog via `POST /jira/sprint-backlog` on the hermes service; the old `JiraClient.get_sprint_backlog` call is gone
  2. `webhook.py` posts draft description comments and architecture comments via `POST /jira/comment` on the hermes service; no `JiraClient` instantiation remains in that module
  3. `approval_detector.py` updates issue descriptions via `PUT /jira/description` and posts approval comments via `POST /jira/comment`; no `JiraClient` instantiation remains
  4. `assign_pipeline.py` assigns issues via `POST /jira/assign` on the hermes service; the separate `lookup_user` + `assign_issue` JiraClient calls are replaced by the single endpoint
  5. `backend/services/jira_client.py` does not exist; `grep -r "JiraClient" backend/` returns no matches; all backend tests pass with hermes API mocks in place of the old JiraClient mock

**Plans**: 3 plans

Plans:

- [ ] 13-01-PLAN.md — Rewrite architecture_pipeline.py: single-pass complexity-aware flow (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-03)
- [x] 13-02-PLAN.md — Webhook idempotency guard + remove architecture approval from approval_detector.py (ARCHINT-01, ARCHINT-02, ARCHINT-03)
- [ ] 13-03-PLAN.md — Replace architecture pipeline tests + add idempotency test to test_webhook.py (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-02)

---

## Milestone v1.4: Smart Architecture & Confluence Publishing

### Phase 10: Complexity Classifier

**Goal**: The agent can reliably classify a requested change as "small" or "complex" using a single low-temperature LLM call with an explicit rubric, and the result plus its rationale are stored in PipelineState for all downstream branches to consume
**Depends on**: Phase 9
**Milestone**: v1.4 — smart-architecture
**Requirements**: CLASSIFY-01, CLASSIFY-02
**Success Criteria** (what must be TRUE):

  1. A single LLM call with `temperature=0` and a structured JSON output schema classifies a ticket as `"small"` or `"complex"` based on the rubric (2+ distinct components, services, or integration points implies "complex")
  2. The classification result and its rationale string are stored on `PipelineState` and retrievable by downstream pipeline stages without making a second LLM call
  3. Unit tests cover the boundary cases — a ticket at threshold-1, threshold, and threshold+1 — and the parse-to-branch logic is tested independently of the LLM call
  4. `complexity_classifier.py` can be imported and called with no database or Jira side effects, confirming it is independently testable

**Plans**: 3 plans

Plans:

- [ ] 13-01-PLAN.md — Rewrite architecture_pipeline.py: single-pass complexity-aware flow (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-03)
- [x] 13-02-PLAN.md — Webhook idempotency guard + remove architecture approval from approval_detector.py (ARCHINT-01, ARCHINT-02, ARCHINT-03)
- [ ] 13-03-PLAN.md — Replace architecture pipeline tests + add idempotency test to test_webhook.py (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-02)

### Phase 11: Enhanced Diagram Service

**Goal**: The diagram service produces mxGraph XML that is validated before use, includes directional edges and typed-component placement, and provides a diagrams.net viewer URL so architects can open and edit diagrams without a Confluence plugin
**Depends on**: Phase 10
**Milestone**: v1.4 — smart-architecture
**Requirements**: ARCHGEN-04, CONFPUB-02
**Success Criteria** (what must be TRUE):

  1. `drawio_service.py` generates mxGraph XML with directional edges between components and typed shapes (e.g. service, database, external system) placed according to component type
  2. Every XML output from `drawio_service` is parse-validated before being returned; malformed XML causes the caller to receive a sentinel value that triggers the text-only degradation path rather than crashing the pipeline
  3. The service returns a `diagrams.net` viewer URL (`https://app.diagrams.net/?xml=<url-encoded-xml>`) alongside the raw XML, allowing an architect to open and edit the diagram in a browser without the draw.io Confluence Marketplace plugin
  4. No new Python packages are introduced; the implementation is pure-Python string building on the existing mxGraph XML builder

**Plans**: 3 plans

Plans:

- [ ] 13-01-PLAN.md — Rewrite architecture_pipeline.py: single-pass complexity-aware flow (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-03)
- [x] 13-02-PLAN.md — Webhook idempotency guard + remove architecture approval from approval_detector.py (ARCHINT-01, ARCHINT-02, ARCHINT-03)
- [ ] 13-03-PLAN.md — Replace architecture pipeline tests + add idempotency test to test_webpack.py (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-02)

### Phase 12: Structured Confluence Publishing

**Goal**: The Confluence client publishes architecture pages using two validated HTML templates, HTML-escapes all LLM-generated text, finds and updates an existing page instead of creating duplicates, and degrades gracefully on publish failure
**Depends on**: Phase 11
**Milestone**: v1.4 — smart-architecture
**Requirements**: CONFPUB-01, CONFPUB-02 (diagram embed), CONFPUB-03, CONFPUB-04
**Success Criteria** (what must be TRUE):

  1. `confluence_client.publish_architecture()` accepts a branch flag and renders one of two HTML templates — text-only (Summary, Approach, Key Decisions, Risks) or diagram+components (Summary, Approach, Component Breakdown, Integration Points, Key Decisions, Risks) — with all LLM-generated text HTML-escaped before interpolation
  2. For diagram pages, the Confluence page body contains a `<pre class="drawio-xml">` block with the raw mxGraph XML and an `<a href="...">` link to the diagrams.net viewer URL so architects can open the diagram without a plugin
  3. Before creating a new page, the client searches for an existing page titled `Architecture: {issue_key}` in the project space and updates it in place if found; a duplicate page is never created for the same ticket
  4. When Confluence publish fails for any reason, a Jira comment is posted with the architecture text inline and no page URL; the pipeline exits cleanly without an unhandled exception

**Plans**: 1 plan
**UI hint**: no

Plans:

**Wave 1**

- [x] 12-01-PLAN.md — confluence_client.py: find_page/update_page idempotent lifecycle, two HTML templates (text-only, diagram+components), HTML-escaping of LLM text, graceful degradation (CONFPUB-01, CONFPUB-02, CONFPUB-03, CONFPUB-04)

### Phase 13: Pipeline Orchestration & Integration

**Goal**: The architecture pipeline is a single-pass flow that classifies, conditionally generates a diagram, publishes to Confluence, and posts back to Jira with the complexity rationale and page link — the old multi-option approval prompt and `_parse_options` logic no longer exist
**Depends on**: Phase 12
**Milestone**: v1.4 — smart-architecture
**Requirements**: ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-01, ARCHINT-02, ARCHINT-03
**Success Criteria** (what must be TRUE):

  1. A `@jarvis architecture` Jira comment mention routes to the new single-architecture pipeline via `KNOWN_STAGES` in `mention_parser.py` and the webhook handler; `_parse_options()` and the "Reply 'approved [option name]'" prompt no longer exist anywhere in `architecture_pipeline.py`
  2. For a "complex" ticket, the pipeline posts a Jira comment containing the architecture summary, the Confluence page URL, and a label such as "Multi-component feature — diagram included"; the Confluence page includes all six structured sections plus the embedded diagram
  3. For a "simple" ticket, the pipeline posts a Jira comment containing the prose architecture and a label such as "Simple change — text architecture"; no diagram is generated and no diagram block appears on the Confluence page
  4. If a second `@jarvis architecture` webhook fires for the same ticket while a pipeline is already active (status not `"failed"`), the webhook returns 200 immediately and the pipeline is not re-triggered
  5. All existing tests pass after the pipeline rewrite; an end-to-end test runs the new pipeline against mocked LLM, diagram, and Confluence calls and asserts that `PipelineState.draft_content` is a well-formed human-readable string (not a JSON blob)

**Plans**: 3 plans
Plans:
**Wave 1**

- [ ] 13-01-PLAN.md — Rewrite architecture_pipeline.py: single-pass complexity-aware flow (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-03)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 13-02-PLAN.md — Webhook idempotency guard + remove architecture approval from approval_detector.py (ARCHINT-01, ARCHINT-02, ARCHINT-03)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 13-03-PLAN.md — Replace architecture pipeline tests + add idempotency test to test_webhook.py (ARCHGEN-01, ARCHGEN-02, ARCHGEN-03, ARCHINT-02)

---

## Milestone v1.5: GitHub Dev Pipeline & LLM Intent Routing

### Phase 14: LLM Intent Router

**Goal**: Free-text `@jarvis` mentions are understood by an LLM classifier instead of a hardcoded keyword whitelist, so developers and team members can trigger actions using natural language; unknown intents surface a helpful reply instead of being silently dropped
**Depends on**: Phase 13
**Milestone**: v1.5 — github-dev-pipeline
**Requirements**: INTENT-01, INTENT-02
**Success Criteria** (what must be TRUE):

  1. A `@jarvis start coding` comment mention is correctly classified by the LLM intent router and routes to the developer coding pipeline handler — the KNOWN_STAGES string-match whitelist in `mention_parser.py` no longer exists
  2. A `@jarvis merge pr to main branch` comment mention is classified as the merge-PR intent and routes to the PR merge handler — natural phrasing variants (e.g. "merge the PR", "merge pr") also resolve to the same intent
  3. When a `@jarvis` comment carries an unrecognized or low-confidence intent, the agent posts a Jira comment listing valid commands (e.g. "`@jarvis start coding`", "`@jarvis merge pr`", "`@jarvis assign @name`") rather than silently dropping the event
  4. Unit tests cover recognized intents, unrecognized intent fallback, and LLM call failure degradation — all without live API keys

**Plans**: 2 plans

Plans:

**Wave 1**

- [x] 14-01-PLAN.md — Create intent_router.py + rewrite mention_parser.py: remove KNOWN_STAGES, wire LLM classifier (INTENT-01)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 14-02-PLAN.md — Update webhook.py: use result.action, post help comment for unrecognized intents + unit tests (INTENT-01, INTENT-02)

### Phase 15: GitHub Config & Dev Pipeline Foundation

**Goal**: Projects can store a GitHub repo slug and the agent can autonomously clone the repo, generate code changes via freellmapi, commit them to a new branch, and open a PR — the pipeline modules exist and are independently testable before end-to-end wiring
**Depends on**: Phase 14
**Milestone**: v1.5 — github-dev-pipeline
**Requirements**: GITHUBCFG-01, GITHUBCFG-02, DEVPIPE-02, DEVPIPE-03, DEVPIPE-04
**Success Criteria** (what must be TRUE):

  1. User can enter a `github_repo` owner/repo slug (e.g. `acme/my-app`) in the project onboarding form and it is saved encrypted in the project DB record alongside the existing credentials
  2. The project dashboard list displays the configured `github_repo` value for each onboarded project
  3. The agent can clone a project's configured GitHub repo to a temporary workspace directory using the stored (decrypted) GitHub token
  4. Given a Jira story description, Confluence architecture content, and cloned codebase context, the agent calls freellmapi to produce code changes and applies them, commits to a new branch named `jarvis/issue-{key}`, pushes the branch, and opens a PR against main via the GitHub API
  5. Each dev pipeline module (clone, code-gen, PR creation) can be tested in isolation with mocked GitHub API and freellmapi responses

**Plans**: 2 plans
Plans:

- [x] 15-01-PLAN.md — Encrypted github_repo config: model column, schemas, router encrypt/decrypt, onboarding form field, dashboard column
- [x] 15-02-PLAN.md — Dev pipeline foundation modules: repo_clone.py, code_generator.py, pr_creator.py (clone, LLM codegen, commit/push/PR)

**UI hint**: yes

### Phase 16: Dev Pipeline Integration

**Goal**: A developer can type `@jarvis start coding` on a Jira story and the agent reads the Confluence architecture page linked in the comment history, runs the dev pipeline, and posts the resulting PR URL back as a new Jira comment — the full trigger-to-PR flow works end-to-end
**Depends on**: Phase 15
**Milestone**: v1.5 — github-dev-pipeline
**Requirements**: DEVPIPE-01, DEVPIPE-05
**Success Criteria** (what must be TRUE):

  1. When the `start_coding` intent is detected, the agent searches the ticket's Jira comment history for the most recent Confluence architecture page URL and fetches the page content via the Hermes Confluence MCP client
  2. After the dev pipeline completes, a new Jira comment on the originating story contains the GitHub PR URL so the developer can navigate directly to the PR from Jira

**Plans**: 2 plans
Plans:

- [x] 16-01-PLAN.md — Comment/Confluence read-path: hermes MCP client + server endpoints + backend hermes_client wrappers + confluence_url_finder utility
- [x] 16-02-PLAN.md — dev_pipeline.py orchestrator wiring read-path through clone/codegen/PR to Jira comment, plus webhook start_coding branch rewire

### Phase 17: PR Merge Pipeline

**Goal**: A developer can type `@jarvis merge pr` on a Jira story and the agent finds the open PR by branch pattern, merges it via the GitHub API, updates the Jira story status, and posts the merge commit SHA back as a Jira comment
**Depends on**: Phase 16
**Milestone**: v1.5 — github-dev-pipeline
**Requirements**: PRMERGE-01, PRMERGE-02
**Success Criteria** (what must be TRUE):

  1. When the `merge_pr` intent is detected, the agent locates the open PR for the story by branch name (`jarvis/issue-{key}`) or PR title match and merges it to main via the GitHub API using the stored project token
  2. After a successful merge, the Jira story status is updated via Hermes/Jira MCP and a new Jira comment contains the merge commit SHA confirming the merge
  3. If no open PR is found for the story, the agent posts an informative Jira comment explaining what was searched and that no PR was found — the pipeline does not raise an unhandled exception

**Plans:** 2/2 plans complete

Plans:

- [x] 17-01-PLAN.md — find_and_merge_pr (GitHub API) + Jira status-update primitives (TDD)
- [x] 17-02-PLAN.md — merge_pipeline orchestrator + webhook.py merge_pr wiring (TDD)

---

## Milestone v1.6: Context-Aware Codebase Scanning ✅ SHIPPED 2026-06-22

### Phase 18: Codebase Scan Service

**Goal**: When a project is onboarded with a `github_repo` field, the agent automatically clones the repo, walks the directory tree with targeted file reads, and commits a structured `.hermes/codebase.md` summary to the main branch — no manual step and no LLM required for the scan itself
**Depends on**: Phase 17
**Milestone**: v1.6 — context-aware-codebase-scanning
**Requirements**: SCAN-01, SCAN-02, SCAN-03
**Success Criteria** (what must be TRUE):

  1. When a project is saved with a `github_repo` value (new onboarding or update), the codebase scan starts automatically — the user takes no additional action
  2. The scan reads only targeted files (README, entry points, config files such as `package.json`, `pyproject.toml`, `__init__.py`) rather than every file in the repo; the directory tree is always included regardless of token cost
  3. A `.hermes/codebase.md` file appears on the main branch containing at minimum: directory tree, detected tech stack, list of key files read, and a module/package summary
  4. The commit is pushed directly to main by the agent using the stored GitHub token — no PR is raised for the snapshot file

**Plans**: 3 plans
Plans:
**Wave 1**

- [x] 18-01-PLAN.md — Async codebase scan service (SCAN-02, SCAN-03): walk GitHub tree, select ≤25 key files, build .hermes/codebase.md, commit via Contents API PUT

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 18-02-PLAN.md — Trigger wiring + tests (SCAN-01): convert create_project to async, schedule background scan task, unit test suite with respx mocks

**Wave 1 (gap closure)**

- [x] 18-03-PLAN.md — Gap closure: regression tests for PipelineState commit + asyncio.create_task scan trigger in test_projects.py (SCAN-01)

### Phase 19: Snapshot Refresh & Read Fallback

**Goal**: The codebase snapshot stays current after each merge and the pipeline never crashes when the snapshot is absent
**Depends on**: Phase 18
**Milestone**: v1.6 — context-aware-codebase-scanning
**Requirements**: SNAPSHOT-01, SNAPSHOT-02
**Success Criteria** (what must be TRUE):

  1. After a successful `@jarvis merge pr` completes, the agent re-clones the repo and pushes an updated `.hermes/codebase.md` to main automatically — the developer takes no additional action
  2. When a pipeline stage attempts to read `.hermes/codebase.md` and the file does not exist on the repo (e.g. scan has never run), the pipeline continues without codebase context and does not raise an exception or return an empty error to the user

**Plans**: 2 plans
Plans:
**Wave 1**

- [x] 19-01-PLAN.md — Post-merge codebase re-scan hook in merge_pipeline.run() (SNAPSHOT-01)
- [x] 19-02-PLAN.md — Standalone get_codebase_snapshot() reader with graceful 404/error fallback (SNAPSHOT-02)

### Phase 20: Describe Pipeline Context

**Goal**: Story elaborations produced by `@jarvis describe` reference real module names and file paths from the codebase instead of generic placeholders
**Depends on**: Phase 19
**Milestone**: v1.6 — context-aware-codebase-scanning
**Requirements**: DESCCTX-01, DESCCTX-02
**Success Criteria** (what must be TRUE):

  1. Before calling freellmapi to generate the elaborated description, `describe_pipeline.py` fetches `.hermes/codebase.md` via the GitHub API and includes its content in the LLM prompt
  2. A generated story elaboration for a project with a committed codebase snapshot contains at least one real module name or file path from the actual repo rather than a generic placeholder such as "the existing services" or "the current codebase"

**Plans**: 1 plan

Plans:

**Wave 1**

- [x] 20-01-PLAN.md — Replace get_codebase_summary with get_codebase_snapshot in describe_pipeline; update tests; add snapshot content assertion (DESCCTX-01, DESCCTX-02)

### Phase 21: Architecture Pipeline Context

**Goal**: Architecture writeups produced by `@jarvis architecture` reference actual existing components, file paths, and integration points rather than invented structure
**Depends on**: Phase 20
**Milestone**: v1.6 — context-aware-codebase-scanning
**Requirements**: ARCHCTX-01, ARCHCTX-02
**Success Criteria** (what must be TRUE):

  1. `architecture_pipeline.py` reads `.hermes/codebase.md` via the GitHub API and includes it in both the complexity classifier LLM call and the architecture generation LLM call — no separate read call for each
  2. A generated architecture writeup for a project with a committed codebase snapshot references at least one actual component name, file path, or integration point from the snapshot rather than invented structure

**Plans**: TBD

---

### Phase 22: Agentic Codegen

**Goal:** Replace freellmapi one-shot codegen with an agentic coding loop: Claude Agent SDK → LiteLLM proxy (Anthropic→OpenAI translation) → freellmapi → free LLMs.

**Deliverables:**

- `litellm/` Docker service + `config.yaml`
- `backend/services/agentic_coder.py`
- Updated `docker-compose.yml`, `dev_pipeline.py`, `requirements.txt`

**Requirements:** `.planning/phases/22-agentic-codegen/22-REQUIREMENTS.md`

---

## Milestone v1.8: Autonomous QA Stage

### Phase 23: QA Foundation & Sandbox Execution

**Goal**: Test and static analysis commands execute safely in an isolated Docker container — the architectural boundary (LLM generates files; orchestrator runs them) is established and validated before any LLM test generation exists
**Depends on**: Phase 22
**Milestone**: v1.8 — autonomous-qa-stage
**Requirements**: TESTEXEC-01, TESTEXEC-02, TESTGEN-02, AUTOFIX-04
**Success Criteria** (what must be TRUE):

  1. Static analysis commands (ruff, mypy, bandit for Python; eslint, tsc, npm audit for JS/TS) run automatically after toolchain auto-detection reads `pyproject.toml`/`setup.cfg` or `package.json` — no LLM call required for this step
  2. Each command executes via `subprocess.run()` inside a fresh cloned workspace with a hard 120-second timeout; captured output is returned as a structured `TestResult` object
  3. The cloned workspace used for QA is always a fresh clone — never the workspace left by the dev or merge pipeline; the workspace is cleaned up after the run regardless of pass or fail outcome
  4. `PipelineState.qa_attempt` field exists and is incremented at the start of each fix attempt, so a mid-loop crash does not restart the counter from zero

**Plans**: 2/2 plans complete
**Wave 1**

- [x] 23-01-PLAN.md — QA sandbox Dockerfile + docker-compose service + PipelineState.qa_attempt column

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 23-02-PLAN.md — test_executor.py toolchain detection + subprocess execution + qa_pipeline.py skeleton

### Phase 24: Test Generation

**Goal**: The agent generates pytest unit tests grounded in the cloned repo's actual code, executes them in the sandbox, and posts the first QA result back to the Jira ticket
**Depends on**: Phase 23
**Milestone**: v1.8 — autonomous-qa-stage
**Requirements**: TESTGEN-01, QAREP-01
**Success Criteria** (what must be TRUE):

  1. Agent calls freellmapi with the cloned repo's file contents and `.hermes/codebase.md` context to generate a pytest unit test file using the `### FILE:` output convention from `code_generator.py`; the generated file is written to the workspace before execution
  2. Generated unit tests execute in the QA sandbox and produce a structured result (pass count, fail count, error output) without requiring any manual configuration of the target repo
  3. After test execution completes (pass or fail), a Jira comment is posted to the originating ticket with a per-category summary covering at minimum: unit tests and static analysis results

**Plans**: 1/1 plans complete

Plans:

- [x] 24-01-PLAN.md — test_generator.py (LLM-grounded pytest generation) + qa_pipeline.py wiring (generate, sandbox-execute, combined Jira report)

### Phase 25: Bounded Auto-Fix Loop

**Goal**: When tests fail, the agent attempts up to 3 targeted fixes using the specific failing output as context, detects non-progress early, and raises fix commits as a PR — never pushing directly to main
**Depends on**: Phase 24
**Milestone**: v1.8 — autonomous-qa-stage
**Requirements**: AUTOFIX-01, AUTOFIX-02, AUTOFIX-03
**Success Criteria** (what must be TRUE):

  1. On test failure, the agent generates a fix via freellmapi using the specific failing test output and error message (not full test regeneration), applies the fix, and re-runs only the failing tests — repeated up to 3 attempts tracked in `PipelineState.qa_attempt`
  2. The loop terminates early when the same error repeats after a fix attempt, so the retry budget is not exhausted on a non-converging failure
  3. Any code changes produced by the auto-fix loop are committed to a branch named `jarvis/qa-fix-{issue_key}` and a PR is opened via `pr_creator.py` — the agent never pushes fix commits directly to main

**Plans**: 1 plan
Plans:

- [ ] 25-01-PLAN.md — auto_fix_loop.py (TDD RED + GREEN), llm_router "autofix" stage, qa_pipeline integration

### Phase 26: E2E + Trigger Wiring

**Goal**: Playwright E2E tests are generated and run when infra exists; both the auto-chain trigger (post-merge) and the on-demand `@jarvis run qa` trigger reach the same QA pipeline with a single idempotency guard preventing duplicate runs
**Depends on**: Phase 25
**Milestone**: v1.8 — autonomous-qa-stage
**Requirements**: TESTGEN-03, QATRIG-01, QATRIG-02, QATRIG-03
**Success Criteria** (what must be TRUE):

  1. When a `playwright.config.*` file is detected in the cloned repo, the agent generates Playwright E2E test(s) grounded in repo context and executes them in the QA sandbox; when no Playwright config is found, a skip note is posted to Jira and no E2E failure is recorded
  2. After a successful PR merge, the QA pipeline starts automatically without any developer action — the merge Jira comment is not delayed by QA startup (fire-and-forget)
  3. A developer can type `@jarvis run qa` on a Jira story to (re-)trigger QA on demand via the LLM intent router
  4. If an active QA `PipelineState` already exists for the ticket (status not `failed`), a duplicate trigger from either path is silently acknowledged with no second pipeline run started

**Plans:** 2 plans

Plans:

- [ ] 26-01-PLAN.md — Playwright E2E generation/execution (TESTGEN-03) + shared has_active_qa_run() guard
- [ ] 26-02-PLAN.md — Auto-chain post-merge trigger + @jarvis run qa comment trigger (QATRIG-01/02/03)

**UI hint**: no

---

<details>
<summary>✅ Milestone v1.9: Playwright E2E Live Testing — SHIPPED 2026-06-26</summary>

- [x] **Phase 27: App Container Service** — app_container.py: detect serve command, ephemeral Docker container on compose network, health-check polling, guaranteed teardown (completed 2026-06-26)
- [x] **Phase 28: QA Pipeline Integration** — wire live container URL as BASE_URL, gate playwright generator on health-check, graceful E2E skip, live URL in Confluence/Jira report (completed 2026-06-26)

Full archive: `.planning/milestones/v1.9-ROADMAP.md`

</details>

## Milestone v2.0: SonarQube QA Integration

- [x] **Phase 29: SonarQube Service Setup** - SonarQube Community Edition on ai-sdlc-net: Docker Compose service, UP health-check readiness poll, bootstrapped admin token on first start (completed 2026-06-27)
- [x] **Phase 30: Scanner Integration** - sonar-scanner QA pipeline step with per-repo project key, CE task API polling, and graceful pipeline continuation on scan failure or timeout (completed 2026-06-27)
- [x] **Phase 31: Confluence Report Section** - SonarQube section appended to existing Confluence QA page: quality gate, metrics table, deep link, and graceful unavailability note (completed 2026-06-27)

## Milestone v2.0: SonarQube QA Integration — Phase Details

### Phase 29: SonarQube Service Setup

**Goal**: SonarQube Community Edition runs persistently on the compose network, is ready before any scan starts, and the scanner has a valid API token to authenticate with
**Depends on**: Phase 28
**Milestone**: v2.0 — sonarqube-qa-integration
**Requirements**: SONAR-01, SONAR-02, SONAR-03
**Success Criteria** (what must be TRUE):

  1. `docker compose up` starts a SonarQube container reachable by other services on ai-sdlc-net; the web UI is accessible on the host at localhost:9000 without manual networking steps
  2. The pipeline waits for SonarQube to report `status=UP` before proceeding — a startup race that triggers a scan against an unready server does not occur
  3. On first boot, an admin API token is created and stored for scanner use; re-running `docker compose up` after the token already exists does not raise an error or create a duplicate token

**Plans**: 2/2 plans complete

- [x] 29-01-PLAN.md
- [x] 29-02-PLAN.md

### Phase 30: Scanner Integration

**Goal**: Every QA pipeline run executes sonar-scanner against the cloned project repo, waits for analysis to complete, and never hard-fails the broader pipeline when SonarQube is unavailable or slow
**Depends on**: Phase 29
**Milestone**: v2.0 — sonarqube-qa-integration
**Requirements**: SCAN-01, SCAN-02, SCAN-03, SCAN-04
**Success Criteria** (what must be TRUE):

  1. A `@jarvis run qa` trigger on a ticket causes a sonar-scanner run against the cloned repo as part of the QA pipeline — the step appears in execution order after static analysis and before Playwright E2E
  2. Projects with different GitHub repo slugs produce separate SonarQube project keys (e.g. `owner1__repo1` vs `owner2__repo2`) so metrics never cross-contaminate between projects
  3. The pipeline waits up to 300 seconds for SonarQube to mark the analysis task SUCCESS before proceeding; the timeout is configurable via environment variable
  4. When SonarQube is down, the scanner exits non-zero, or the CE task times out, the QA pipeline logs the failure, records a scan-unavailable result, and continues to the next step — the overall QA run is not aborted

**Plans**: 2/2 plans complete

Plans:

- [x] 30-02-PLAN.md

- [x] 30-01-PLAN.md — sonar-scanner module + CE task polling wired into QA pipeline (SCAN-01..04)

### Phase 31: Confluence Report Section

**Goal**: Every Confluence QA page produced by the pipeline includes a SonarQube section with actionable quality metrics and a direct link to the dashboard, and shows a clear fallback when the scan did not run
**Depends on**: Phase 30
**Milestone**: v2.0 — sonarqube-qa-integration
**Requirements**: REPORT-01, REPORT-02, REPORT-03
**Success Criteria** (what must be TRUE):

  1. After a QA run with a successful scan, the Confluence QA page contains a SonarQube section positioned after the existing test results — the page is visibly updated and the section header is present
  2. The SonarQube section displays: quality gate status (PASSED/FAILED), bug count, vulnerability count, code smell count, coverage percentage, duplications percentage, and a hyperlink that opens the SonarQube project dashboard directly
  3. When the scan was skipped or failed, the Confluence page shows "SonarQube scan unavailable" in the SonarQube section rather than an empty block or a rendering error

**Plans**: 1/1 plans complete

Plans:

- [x] 31-01-PLAN.md — SonarMetrics fetch, Confluence section rendering, pipeline wiring

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 19 → 20 → 21 → 22 → 23 → 24 → 25 → 26 → 27 → 28 → 29 → 30 → 31

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 2/2 | Complete | 2026-06-18 |
| 2. Web App | 2/2 | Complete | 2026-06-18 |
| 3. Description Elaboration | 2/2 | Complete | 2026-06-18 |
| 4. Architecture Pipeline | 2/2 | Complete | 2026-06-18 |
| 5. freellmapi Integration | 2/2 | Complete | 2026-06-18 |
| 6. Hermes LLM Client | 2/2 | Complete | 2026-06-18 |
| 7. MCP Infrastructure | 0/1 | Not started | - |
| 8. Hermes MCP Client + Internal API | 0/? | Not started | - |
| 9. Backend Migration | 0/? | Not started | - |
| 10. Complexity Classifier | 2/2 | Complete   | 2026-06-19 |
| 11. Enhanced Diagram Service | 1/1 | Complete   | 2026-06-19 |
| 12. Structured Confluence Publishing | 0/1 | Not started | - |
| 13. Pipeline Orchestration & Integration | 1/3 | In Progress | - |
| 14. LLM Intent Router | 2/2 | Complete   | 2026-06-20 |
| 15. GitHub Config & Dev Pipeline Foundation | 2/2 | Complete    | 2026-06-20 |
| 16. Dev Pipeline Integration | 2/2 | Complete   | 2026-06-21 |
| 17. PR Merge Pipeline | 2/2 | Complete    | 2026-06-21 |
| 18. Codebase Scan Service | 4/4 | Complete    | 2026-06-22 |
| 19. Snapshot Refresh & Read Fallback | 2/2 | Complete   | 2026-06-22 |
| 20. Describe Pipeline Context | 1/1 | Complete    | 2026-06-22 |
| 21. Architecture Pipeline Context | 1/1 | Complete   | 2026-06-22 |
| 22. Agentic Codegen              | 1/1 | Complete   | 2026-06-23 |
| 23. QA Foundation & Sandbox Execution | 2/2 | Complete    | 2026-06-23 |
| 24. Test Generation | 1/1 | Complete    | 2026-06-24 |
| 25. Bounded Auto-Fix Loop | 0/? | Not started | - |
| 26. E2E + Trigger Wiring | 0/? | Not started | - |
| 27. App Container Service | 1/1 | ✅ Complete (v1.9) | 2026-06-26 |
| 28. QA Pipeline Integration | 1/1 | ✅ Complete (v1.9) | 2026-06-26 |
| 29. SonarQube Service Setup | 2/2 | Complete    | 2026-06-27 |
| 30. Scanner Integration | 2/2 | Complete   | 2026-06-27 |
| 31. Confluence Report Section | 1/1 | Complete    | 2026-06-27 |
