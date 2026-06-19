# Architecture Research

**Domain:** Integration of new "Smart Architecture & Confluence Publishing" flow into existing Jira-comment-driven SDLC agent pipeline
**Researched:** 2026-06-19
**Confidence:** HIGH (based on direct reading of existing codebase, not external sources)

## Standard Architecture

### System Overview (current, validated against code)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Jira Cloud                                                               │
│   comment event → POST /webhook/jira-comment                            │
└───────────────────────────┬───────────────────────────────────────────────┘
                            │
┌───────────────────────────▼───────────────────────────────────────────────┐
│ backend/routers/webhook.py                                               │
│  - verify_webhook_secret()                                               │
│  - resolve Project by project_key                                       │
│  - ignore self-authored agent comments (AGENT_BODY_MARKER)              │
│  - mention_parser.parse_mention(comment.body) → MentionResult|None      │
│  - if mention: dispatch by mention_result.stage                         │
│      "describe"      → describe_pipeline.run() (awaited)                │
│      "architecture"  → architecture_pipeline.run() (asyncio.create_task)│
│      "assign"        → assign_pipeline.run() (awaited)                  │
│      other known     → llm_router.route_request() (legacy passthrough)  │
│  - if no mention: approval_detector.detect_and_apply_approval()         │
└───────────────────────────┬───────────────────────────────────────────────┘
                            │
        ┌───────────────────┼─────────────────────────────┐
        ▼                   ▼                             ▼
┌───────────────┐  ┌──────────────────────┐   ┌──────────────────────────┐
│describe_       │  │architecture_         │   │assign_pipeline.py        │
│pipeline.py     │  │pipeline.py (TO BE     │   │ (pattern reference for  │
│                │  │ REPLACED this milestone)│   │  new architecture flow) │
└───────┬────────┘  └──────────┬───────────┘   └──────────────────────────┘
        │                      │
        ▼                      ▼
┌───────────────┐    ┌───────────────────────┐      ┌────────────────────┐
│llm_router.py   │    │drawio_service.py       │      │confluence_client.py │
│ route_request()│    │ generate_diagram()      │      │ publish_architecture │
│ → freellmapi   │    │ (hand-rolled mxGraph,   │      │ (direct REST,        │
│   (Ollama)     │    │  TO BE REPLACED)        │      │  httpx + Basic auth, │
└───────────────┘    └───────────────────────┘      │  NOT via MCP)        │
                                                      └──────────┬───────────┘
                                                                 │
┌────────────────────────────────────────────────────────────────▼──────────┐
│hermes_client.py (thin async httpx wrapper)                                │
│  post_comment / put_description / post_sprint_backlog / post_assign       │
│   → calls hermes container's internal /jira/* FastAPI endpoints           │
└───────────────────────────┬─────────────────────────────────────────────┘
                            ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ hermes/server.py  (FastAPI, internal-only, no auth — same Docker network) │
│  /jira/comment, /jira/description, /jira/sprint-backlog, /jira/assign     │
│   → HermesMCPClient (hermes/mcp_client.py)                                │
│      add_comment / update_description / get_sprint_issues /               │
│      lookup_user / assign_issue  — NO Confluence tool wrappers exist yet  │
└───────────────────────────┬─────────────────────────────────────────────┘
                            ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ mcp-atlassian Docker service (sooperset/mcp-atlassian), MCP/SSE          │
│  supports both Jira AND Confluence tools — only Jira tools are wired      │
│  through Hermes today; Confluence side is unused by this codebase        │
└───────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities (existing, named files)

| Component | Responsibility | File |
|-----------|----------------|------|
| Webhook router | Auth, project resolution, self-comment dedup, mention dispatch | `backend/routers/webhook.py` |
| Mention parser | Regex-extract `@agent stage [extra]`, validate against `KNOWN_STAGES` | `backend/services/mention_parser.py` |
| Pipeline stage handlers | One module per stage (`describe`, `architecture`, `assign`); each owns its own prompt-building, LLM call, side-effecting Jira write, and `PipelineState` persistence | `backend/services/describe_pipeline.py`, `architecture_pipeline.py`, `assign_pipeline.py` |
| LLM router | Route prompt to freellmapi (Ollama, heavy stages) or main model stub | `backend/services/llm_router.py` |
| Diagram generator | Hand-rolled mxGraph XML string builder (no drawio-skill integration yet) | `backend/services/drawio_service.py` |
| Confluence client | Direct REST (httpx + Basic auth), independent of MCP layer | `backend/services/confluence_client.py` |
| Hermes HTTP wrapper | Thin async httpx client calling hermes's internal `/jira/*` endpoints | `backend/services/hermes_client.py` |
| Hermes internal server | FastAPI app exposing `/jira/*`; delegates to `HermesMCPClient` | `hermes/server.py` |
| Hermes MCP client | Typed async wrappers over mcp-atlassian's MCP/SSE tool calls (Jira only) | `hermes/mcp_client.py` |
| Pipeline state | SQLAlchemy model tracking `pending → processing → awaiting_approval → approved/failed` per (project, ticket, stage) | `backend/models/pipeline_state.py` |
| Approval detector | Scans plain (non-mention) comments for approval keywords, applies the previously drafted change | `backend/services/approval_detector.py` |

## Recommended Integration Approach

### Routing layer (webhook.py + mention_parser.py): minimal change

`mention_parser.py`'s `KNOWN_STAGES` already includes `"architecture"` and the parser already captures `extra` trailing tokens after the stage keyword. **No new stage keyword is needed** — `"@jarvis architecture"` already parses to `MentionResult(stage="architecture", extra="")`. This milestone does not need a new mention grammar; it replaces what happens when `stage == "architecture"` fires.

**Modify in place:** `webhook.py`'s `elif mention_result.stage == "architecture":` branch. Today it calls `architecture_pipeline.run(project, event.issue.key, issue_summary, issue_description, db)` as a fire-and-forget `asyncio.create_task`. Keep this exact shape (background task, same signature pattern) — only the callee changes. This preserves the async/background-task convention already established for the one other heavy-LLM stage handler.

### New vs. modified components

| Component | New or Modified | Rationale |
|-----------|------------------|-----------|
| `backend/services/architecture_pipeline.py` | **Replace in place** (same filename/module path, full rewrite of internals) | `webhook.py` already imports and calls `architecture_pipeline.run(...)`; keeping the module path stable means **zero changes to webhook.py's import line**, only the call-signature/body of `run()` changes if needed. Renaming this module would force an extra edit to `webhook.py` and to `test_architecture_pipeline.py` for no benefit — the "multi-option" logic this milestone removes (`_build_prompt`, `_parse_options` for 2-3 options) is exactly what's inside this file's private functions, so a rewrite of the same file is the correct unit of change, not a parallel module. |
| `backend/services/complexity_classifier.py` | **New module** | The complexity decision (text-only vs. diagram+components) is a distinct, independently testable concern — an LLM-judged classification step with its own prompt, parsing, and confidence/fallback logic. Keeping it as its own module (rather than inlining into `architecture_pipeline.py`) lets it be unit-tested in isolation (mirrors how `mention_parser.py` is separate from `webhook.py`) and reused if a future stage also needs a complexity gate. `architecture_pipeline.py` becomes the *orchestrator* that calls `complexity_classifier.classify(...)` then branches. |
| `backend/services/drawio_service.py` | **Replace in place** (same filename, internals swapped for real drawio-skill integration) | Same reasoning as `architecture_pipeline.py`: `architecture_pipeline.py` already imports `generate_diagram` from this module path; replacing the implementation (hand-rolled mxGraph → real Agents365-ai/drawio-skill call) without renaming avoids cascading import changes. If the drawio-skill integration approach (vendored Python vs. shell-out to Claude Code, decided in separate research) requires a fundamentally different call signature (e.g. async subprocess invocation vs. pure-Python string builder), that's still a body-of-function change, not a reason to rename the module — keep `generate_diagram()` as the public entry point and change its internals/signature as needed. |
| `backend/services/confluence_client.py` | **Modify in place, minimally** — keep direct REST | See "Confluence: REST vs MCP" below. Only change: the page template/builder for "single recommended architecture" content (was: N options text + N diagram XMLs; becomes: one classification result + zero-or-one diagram). The `ConfluenceClient` class and `publish_architecture()`-style entry point structure stay; only the body-construction logic changes. |
| `backend/services/hermes_client.py` | **No change** | This milestone's Jira write-back ("comment posted back referencing Confluence page URL") is a plain `post_comment(...)` call — identical to the existing pattern used by `describe_pipeline` → `webhook.py` and by `assign_pipeline.py`. No new hermes_client function needed. |
| `backend/routers/webhook.py` | **Modify in place, one branch only** | Same `elif mention_result.stage == "architecture":` block; only the call target's internals change (still `architecture_pipeline.run(...)` as background task). No new branch, no new stage keyword. |
| `backend/models/pipeline_state.py` | **No schema change** | `status` lifecycle (`pending → processing → awaiting_approval → approved/failed`) and `draft_content: Text` already generically fit storing either a text-only architecture decision or a diagram+components write-up. No new column needed unless the team wants to persist the Confluence page URL structurally (optional — currently `architecture_pipeline.py` embeds the URL directly into the Jira comment text rather than a dedicated column; this convention can continue).
| `backend/tests/test_architecture_pipeline.py`, `test_drawio_service.py` | **Modify in place** | Existing test files target the same module paths; since those modules are replaced in place (not renamed), the existing test files are the natural home for new test cases — old multi-option test cases get removed/rewritten, not orphaned. |

**Key principle driving "replace in place" vs. "new module":** every place `webhook.py` or `architecture_pipeline.py` currently has an *import statement* pointing at a stable module path stays a replace-in-place to avoid blast-radius in the router (the one file the milestone explicitly should NOT need to restructure beyond the single existing branch). Every place there's a *new independently-testable decision* (complexity classification) becomes a new module, mirroring how `mention_parser.py` was split out from `webhook.py` rather than inlined.

## Confluence: REST vs MCP — recommendation is to leave REST as-is for this milestone

**Verdict: do NOT migrate Confluence to MCP in this milestone.** Reasons, in order of weight:

1. **Scope discipline.** The milestone's stated target features are: new mention trigger, complexity classifier, real drawio-skill integration, single-page Confluence publish, Jira comment-back, and removal of the old multi-option flow. Migrating Confluence to MCP is explicitly the kind of cross-cutting infra change that was its own milestone for Jira (v1.3 "Hermes MCP Agent") — bundling a second MCP migration into a feature milestone repeats the same risk profile (new transport layer, new credential-passing pattern, new container wiring) for a capability (page publish/update) that already works reliably over plain REST today, with **no functional requirement** in this milestone's feature list demanding MCP specifically.
2. **mcp-atlassian *does* support Confluence tools** (confirmed: sooperset/mcp-atlassian exposes both Jira and Confluence MCP tools), so a future "Confluence MCP" milestone remains straightforward — nothing in this milestone forecloses it. The architecture is already structured so that `confluence_client.py` is a swappable boundary (it's already isolated from the Jira/MCP layer, exactly the seam a future migration would target).
3. **Today's REST path already has the encryption/auth pattern needed** (`decrypt_credential`, Basic auth header construction, 30s timeout, graceful degradation on failure) — this is proven and tested (`test_confluence_client.py` exists). Re-deriving equivalent per-request credential passing through `HermesMCPClient` (which currently only wraps Jira tools — `add_comment`, `update_description`, `get_sprint_issues`, `lookup_user`, `assign_issue`, with **no Confluence wrapper methods present**) would require: (a) adding Confluence tool methods to `hermes/mcp_client.py`, (b) adding `/confluence/*` endpoints to `hermes/server.py`, (c) adding a `hermes_client.py` wrapper function, (d) deleting `confluence_client.py` — a 4-file change purely for parity, not for new capability.
4. **Graceful-degradation behavior must be preserved regardless.** The existing `architecture_pipeline.py` pattern (`T-04-03`: catch all exceptions from `publish_architecture`, continue with `page_url = ""`) is the right pattern to carry forward verbatim into the new flow, independent of REST vs MCP.

**Recommendation for what *does* change in confluence_client.py this milestone:** only the page-body template function — replace "N options, each with diagram" structure with "one recommendation, optionally with one diagram embed" structure. Function/class names and the REST transport stay untouched.

If a future milestone explicitly needs Confluence MCP (e.g., to reuse mcp-atlassian's structured Confluence search/CQL tools for something beyond simple page creation), that should be its own scoped milestone, following the same playbook as v1.3.

## Data Flow (new architecture flow)

```
Jira comment "@jarvis architecture [optional extra text]"
        │
        ▼
webhook.py: parse_mention() → MentionResult(stage="architecture")
        │  (existing branch, asyncio.create_task — no change to dispatch)
        ▼
architecture_pipeline.run(project, issue_key, issue_summary, issue_description, db)
        │
        ├─► PipelineState row created: stage="architecture", status="processing"
        │
        ▼
complexity_classifier.classify(issue_summary, issue_description)
        │   LLM call via llm_router.route_request("architecture", classification_prompt)
        │   returns e.g. ComplexityResult(depth="text_only"|"diagram", components=[...])
        │
        ├── depth == "text_only" ──────────────┐
        │                                       │
        ▼                                       ▼
   skip drawio_service.generate_diagram()   drawio_service.generate_diagram(
        │                                     title, components, connections)
        │                                       │  (real Agents365-ai/drawio-skill call,
        │                                       │   integration approach decided separately)
        └───────────────┬───────────────────────┘
                         ▼
        Build single recommendation write-up (text, + diagram XML if applicable)
                         ▼
        confluence_client.publish_architecture(project, issue_key, recommendation_text,
                                                 diagram_xml | None)
                         │  graceful degradation: catch all exceptions → page_url = ""
                         ▼
        Compose Jira comment text: AGENT_COMMENT_PREFIX + AGENT_BODY_MARKER +
                                    recommendation summary + Confluence URL (or degraded note)
                         ▼
        hermes_client.post_comment(jira_url, jira_email, jira_token, issue_key, comment_text)
                         │  (existing function, no change — same call shape as describe_pipeline)
                         ▼
        PipelineState updated: status="awaiting_approval", draft_content=recommendation_text
                         ▼
        Architect replies "lgtm" (or similar) in Jira comment thread
                         ▼
        webhook.py: mention_result is None → approval_detector.detect_and_apply_approval()
                         │  (existing approval flow — verify it already generically handles
                         │   stage="architecture" PipelineState rows; if not, this is a
                         │   small required modification, not a new component)
```

## Suggested Build Order

Ordered by hard dependency — each step's testable surface depends on the previous step existing, mirroring how `mention_parser.py` was built/tested before `webhook.py`'s dispatch logic depended on it.

1. **`complexity_classifier.py` (new module)** — Build and unit-test in isolation first. It has no dependency on diagram generation or Confluence; it only needs `llm_router.route_request()` (already exists) and a prompt template. Testable with mocked LLM responses, exactly like the existing `_parse_options` tests in `test_architecture_pipeline.py` today.

2. **`drawio_service.py` replacement (real drawio-skill integration)** — Depends on the separately-researched integration decision (vendor vs. shell-out), but does **not** depend on the classifier. Can be built/tested in parallel with step 1 once the integration approach is chosen, since `generate_diagram(title, components, connections)` keeps the same signature shape as today and can be tested standalone with a fixed components list.

3. **`confluence_client.py` page-builder update** — Depends on knowing the final shape of (a) the classifier's output structure (to decide what text sections appear) and (b) the diagram module's output format (XML string or file reference) so the page template can embed it correctly. Should follow steps 1 and 2, but is otherwise independent of webhook wiring — testable with a stub recommendation object and stub diagram XML.

4. **`architecture_pipeline.py` rewrite (orchestration)** — Wires together steps 1–3: calls classifier, conditionally calls diagram generator, builds recommendation text, calls Confluence publish, calls `hermes_client.post_comment`, persists `PipelineState`. This must come after 1–3 exist (even as early/stubbed versions) since it imports and calls all three.

5. **`webhook.py` branch verification** — Last, and lowest-risk: confirm the existing `elif mention_result.stage == "architecture":` branch's call signature to `architecture_pipeline.run(...)` still matches (it should, if step 4 preserves the existing `run()` signature). If `approval_detector.py` needs a stage-specific branch for applying the architecture decision post-approval, validate/extend that here as the final integration check, then run the full webhook-level integration test (`test_webhook.py`) to confirm the end-to-end comment → classify → diagram → publish → comment-back flow.

**Old module removal** (`_build_prompt`/`_parse_options` multi-option logic inside `architecture_pipeline.py`, and the old hand-rolled mxGraph cell-layout logic inside `drawio_service.py`) happens as part of steps 2 and 4 respectively — since those are in-place rewrites, deletion of old logic is concurrent with addition of new logic in the same file/PR, not a separate cleanup step.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Creating `architecture_pipeline_v2.py` alongside the old file

**What people do:** Add a new module instead of replacing the old one, to "avoid breaking things."
**Why it's wrong:** `webhook.py` has exactly one import site and one call site for this module. There is no parallel caller that needs the old multi-option behavior preserved (the milestone explicitly says "removal/replacement" of the old flow). A v2 file creates dead code, an extra import to clean up later, and two test files to maintain in the interim.
**Do this instead:** Rewrite `architecture_pipeline.py` and `drawio_service.py` in place; rely on git history (not a parallel file) if the old multi-option logic ever needs to be referenced.

### Anti-Pattern 2: Inlining the complexity classification into `architecture_pipeline.py`

**What people do:** Add an `if "small change" in description.lower()` heuristic or an inline LLM call directly inside `run()`.
**Why it's wrong:** Mirrors the mistake `mention_parser.py`'s extraction avoided — an undertested, unreusable decision embedded in an orchestration function. It also makes `architecture_pipeline.py`'s tests have to mock/stub the classification logic every time, rather than mocking one clean function call.
**Do this instead:** Isolate as `complexity_classifier.py` with its own prompt builder, LLM call, and result dataclass (mirroring the `MentionResult` / `LLMResponse` dataclass conventions already used elsewhere in this codebase).

### Anti-Pattern 3: Migrating Confluence to MCP "while we're in here"

**What people do:** Since the team just did the Jira MCP migration (v1.3), there's a temptation to finish the job for Confluence in the same milestone, for architectural symmetry.
**Why it's wrong:** Expands blast radius into `hermes/mcp_client.py` and `hermes/server.py` — files this milestone's stated scope does not otherwise touch — for a transport change with no new functional requirement, increasing risk of regressions in an unrelated, already-working REST path.
**Do this instead:** Ship this milestone with Confluence on REST; track an MCP-Confluence migration as its own future milestone if/when a concrete requirement (e.g., CQL search, page tree navigation) needs MCP-specific Confluence tools.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| freellmapi (Ollama) | `llm_router.route_request(stage, prompt)` → OpenAI-compatible `/v1/chat/completions` | Already used by `describe_pipeline.py` and the old `architecture_pipeline.py`; the new classifier and the diagram-recommendation prompt both reuse this same entry point with `stage="architecture"` (already in `HEAVY_STAGES`). |
| mcp-atlassian (Jira tools) | `hermes_client.post_comment()` → hermes `/jira/comment` → `HermesMCPClient.add_comment()` | No change needed; reused as-is for the final Jira comment-back. |
| mcp-atlassian (Confluence tools) | **Not used** — REST direct via `confluence_client.py` | Available in the underlying mcp-atlassian image but deliberately out of scope this milestone (see recommendation above). |
| Agents365-ai/drawio-skill | New: replaces hand-rolled XML in `drawio_service.py` | Integration approach (vendored Python module vs. shell-out/subprocess to a Claude Code-style invocation) is decided in separate research; whichever is chosen, keep `generate_diagram(title, components, connections) -> str` (or equivalent) as the stable function signature `architecture_pipeline.py` calls, so the orchestrator doesn't need to know which integration strategy is in use. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `webhook.py` ↔ `architecture_pipeline.py` | Direct async function call (`asyncio.create_task`, fire-and-forget) | Unchanged signature pattern: `run(project, issue_key, issue_summary, issue_description, db)`. |
| `architecture_pipeline.py` ↔ `complexity_classifier.py` | Direct async function call | New boundary; classifier should be a pure function of (summary, description) → result, no DB/Jira side effects, easy to unit test. |
| `architecture_pipeline.py` ↔ `drawio_service.py` | Direct function/async call | Keep signature stable across the drawio-skill integration swap. |
| `architecture_pipeline.py` ↔ `confluence_client.py` | Direct async call, wrapped in try/except for graceful degradation (existing `T-04-03` pattern) | Preserve the "continue without URL on failure" behavior. |
| `architecture_pipeline.py` ↔ `hermes_client.py` | Direct async call (`post_comment`) | Identical call shape to `describe_pipeline.py`'s usage — no new wrapper needed. |
| `approval_detector.py` ↔ `PipelineState` (stage="architecture") | DB query/update | Verify existing approval-detection logic already generically handles any `stage` value, or needs a small architecture-specific branch for "apply the recommendation" semantics (e.g., does approval of an architecture page require any Jira-side write beyond acknowledgment, unlike `describe`'s `put_description`?). This is the one place worth double-checking during step 5 of the build order. |

## Sources

- Direct reading of: `backend/routers/webhook.py`, `backend/services/mention_parser.py`, `backend/services/architecture_pipeline.py`, `backend/services/drawio_service.py`, `backend/services/confluence_client.py`, `backend/services/hermes_client.py`, `backend/services/describe_pipeline.py`, `backend/services/assign_pipeline.py`, `backend/services/llm_router.py`, `backend/models/pipeline_state.py`, `hermes/server.py`, `hermes/mcp_client.py` — all read in full or substantial part during this research session (2026-06-19).
- `.planning/PROJECT.md` — milestone v1.4 scope and v1.3 (Hermes MCP Agent) completed-milestone context.

---
*Architecture research for: AI-SDLC Jira — v1.4 Smart Architecture & Confluence Publishing*
*Researched: 2026-06-19*
