# Project Research Summary

**Project:** AI-SDLC Jira — v1.4 Smart Architecture & Confluence Publishing
**Domain:** LLM-driven SDLC automation embedded in Jira comment history
**Researched:** 2026-06-19
**Confidence:** HIGH (architecture/codebase-grounded), MEDIUM (features/pitfalls patterns)

## Executive Summary

Milestone v1.4 replaces the existing multi-option architecture approval flow with a single-pass, complexity-aware pipeline: when a team member triggers `@jarvis architecture` in a Jira comment, the agent classifies the ticket as "small" (text-only) or "complex" (diagram + component breakdown), generates the appropriate Confluence page, and posts a comment back with the link and classification rationale. The core insight from research is that this is fundamentally a rewrite-in-place, not a new feature addition — `architecture_pipeline.py` and `drawio_service.py` are replaced in their existing module paths so the webhook router requires minimal changes. A new `complexity_classifier.py` module is the only net-new component, deliberately isolated for independent testability.

The recommended approach avoids all net-new dependencies. The existing `openai` SDK (via `HermesLLMClient`), `httpx` (`ConfluenceClient`), and `SQLAlchemy` (`PipelineState`) cover every requirement. The drawio-skill (Agents365-ai/drawio-skill) is an AI agent instruction file, not a Python library or HTTP service — shelling out to it from a Docker container without the draw.io desktop binary is a dead end. The correct integration is to enhance the existing mxGraph XML string builder in `drawio_service.py` with better layout logic (directional edges, typed-component placement), which is pure Python string building with no new packages. For Confluence diagram embedding, the XML-in-a-`<pre>`-block approach already in `confluence_client.py` is correct; adding a diagrams.net viewer URL is the only enhancement needed.

The key risks cluster around three areas: (1) non-deterministic LLM complexity classification flipping between runs — mitigated by a structured rubric with explicit numeric thresholds, low-temperature classification call, and an idempotency guard on the webhook handler (currently missing, confirmed absent in codebase); (2) malformed Confluence HTML from two divergent branch templates — mitigated by HTML-escaping all LLM output and XML-validating both templates in tests; and (3) the `approval_detector.py` contract with `PipelineState.draft_content` silently breaking if the pipeline rewrite stores structured data there instead of a ready-to-post text string. All three are avoidable with upfront design decisions rather than post-hoc fixes.

## Key Findings

### Recommended Stack

No new dependencies are required for v1.4. The existing stack covers all capability needs: `openai` SDK for the complexity classification LLM call (one `HermesLLMClient.chat()` call parsed as a 1-token `small`/`complex` string), `httpx` for Confluence REST calls, and `SQLAlchemy` for pipeline state persistence. The drawio-skill integration resolves to enhancing the existing in-memory mxGraph XML builder — not a subprocess call, not `drawpyo`, not the draw.io desktop app.

**Core technologies (all existing, no additions):**
- `FastAPI 0.115.5` (backend): webhook receiver and API — unchanged
- `openai >=1.0` (hermes): `HermesLLMClient.chat()` reused for classification prompt at `temperature=0.0`
- `httpx 0.28.1` (backend): `ConfluenceClient` REST calls — signature change only, transport unchanged
- `SQLAlchemy 2.0.36` (backend): `PipelineState` persistence — no schema change required for MVP
- Enhanced `drawio_service.py`: in-memory mxGraph XML with directional edge logic — pure Python, no new deps

**What not to add:** draw.io desktop headless Docker image (500MB, requires xvfb), drawpyo (writes to disk, no capability gain at this scope), atlassian-python-api (duplicates existing ConfluenceClient), instructor/pydantic-ai (overkill for a 1-token classification parse), rlespinasse/drawio-desktop-headless (same bloat problem).

### Expected Features

**Must have (table stakes — v1.4 launch):**
- `@jarvis architecture` comment trigger — existing mention grammar already parses this; no new stage keyword needed
- Single LLM classification call returning structured output with explicit rubric (component count, integration points, data model changes, new external deps)
- Exactly one recommended architecture output — removes `_parse_options` multi-option parsing entirely
- Two-tier Confluence page templates gated by complexity: small = prose summary/rationale/trade-offs; complex = same plus component list, integration points, and one diagram
- At least one component-level diagram for "complex" tickets (mxGraph XML enhanced in-place)
- `confluence_client.py` updated to accept structured sections instead of one flat text blob
- Jira comment posted back with Confluence link and visible complexity label
- Graceful degradation on Confluence publish failure (existing T-04-03 pattern carried forward)

**Should have (v1.4.x follow-on):**
- Idempotent Confluence page updates (find-by-title + update instead of always-create)
- Hybrid rule-based pre-filter before LLM classification call (keyword/component-count guardrail for obvious cases)
- Structured override re-trigger (`@jarvis architecture force-complex`)

**Defer (v2+):**
- Multi-tier complexity scale beyond binary (no standard practice justifies more than 2 tiers at this stage)
- Multiple C4 diagram levels — one component-level diagram is sufficient per C4 guidance
- Learned/trained complexity classifier — LLM call with rubric is sufficient at current volume

### Architecture Approach

This milestone is a surgical rewrite of two existing modules (`architecture_pipeline.py`, `drawio_service.py`) plus a targeted update to `confluence_client.py`, with one new module (`complexity_classifier.py`). The webhook router requires only a call-signature verification. Confluence integration stays on direct REST — migrating to MCP would expand blast radius into `hermes/mcp_client.py` and `hermes/server.py` with no new functional requirement and is explicitly deferred.

**Major components (new or changed):**
1. `complexity_classifier.py` (NEW) — LLM classification call via `llm_router.route_request()`, returns structured `ComplexityResult(depth, components, classification_reason)`; independently unit-testable with no DB/Jira side effects
2. `architecture_pipeline.py` (REWRITE IN PLACE) — orchestrator calling classifier → conditionally calls diagram generator → calls Confluence publish → calls `hermes_client.post_comment` → persists `PipelineState`
3. `drawio_service.py` (ENHANCE IN PLACE) — improved mxGraph XML layout with directional edge logic; keeps `generate_diagram(title, components, connections) -> str` signature stable
4. `confluence_client.py` (MODIFY IN PLACE) — updated `publish_architecture()` signature accepting structured sections; two HTML templates; diagrams.net viewer URL added to diagram embed
5. `webhook.py` (VERIFY + PATCH) — confirm existing `elif mention_result.stage == "architecture":` branch; add idempotency/supersede check for duplicate webhooks (currently missing)

### Critical Pitfalls

1. **Classification non-determinism (flip-flops between runs)** — Use low/zero temperature for the classification call, structured JSON output with explicit numeric rubric, and an idempotency guard in `webhook.py`'s architecture branch (currently absent). Add a `complexity` column to `PipelineState` so decisions are queryable.

2. **Malformed Confluence HTML across two branch templates** — HTML-escape all LLM-generated text (`html.escape()`) before template interpolation. Unit-test each template with `xml.etree.ElementTree.fromstring`. Log HTTP status codes distinctly (4xx = malformed body vs. 5xx = transient) so the catch-all does not hide content errors.

3. **drawio output treated as reliable when it is not** — Validate the mxGraph XML output before embedding in Confluence (parse returned XML, verify node IDs referenced in edges exist). Wrap with explicit timeout and fallback to text-only degradation path, not a crash.

4. **`approval_detector.py` contract breakage after pipeline rewrite** — `draft_content` in `PipelineState` has an implicit "ready to post verbatim to Jira" contract. The new pipeline must persist a flat human-readable text string (summary + Confluence link), never a JSON blob. Store structured metadata in new columns. Add an end-to-end test: new pipeline run → `PipelineState.draft_content` → simulated "lgtm" → assert posted Jira comment is well-formed text.

5. **Testing only obvious classification extremes, not boundary cases** — The rubric defines a threshold. Test at threshold-1, threshold, threshold+1. Separate deterministic "parse LLM structured output → branch enum" logic (unit-testable) from "ask LLM to judge" (periodic eval set, not every CI run).

## Implications for Roadmap

Based on research, the milestone decomposes into 4 phases ordered by hard dependency:

### Phase 1: Complexity Classifier
**Rationale:** All downstream branches depend on the classification decision being stable and auditable. Get the rubric, structured output, idempotency guard, and boundary-case test plan right before building anything that branches on the result.
**Delivers:** `complexity_classifier.py` with structured JSON output, explicit rubric (2+ distinct components/integration points → complex), low-temperature classification call, and a boundary-focused test suite
**Addresses:** Single LLM classification call (P1 feature), classification rationale surfaced in output (P2 feature)
**Avoids:** Pitfall 1 (classification flip-flops), Pitfall 5 (undertested boundary cases)

### Phase 2: Enhanced Diagram Service
**Rationale:** `drawio_service.py` is independently testable with no classifier dependency. Can proceed in parallel with Phase 1 once the output signature is agreed. Must be proven reliable with output validation before being wired into the Confluence publish step.
**Delivers:** Enhanced in-place `drawio_service.py` with directional edge layout (API Gateway → Service → Database typed placement), XML output validation, and explicit fallback-to-text degradation path; diagrams.net viewer URL for plugin-agnostic Confluence embed
**Uses:** Existing in-memory mxGraph XML builder (no new deps)
**Avoids:** Pitfall 3 (diagram output treated as reliable without validation)

### Phase 3: Structured Confluence Publishing
**Rationale:** Depends on knowing the classifier's output shape (Phase 1) and diagram output format (Phase 2) before building two branch templates. Both templates need equal test rigor — the simpler text-only branch is historically undertested.
**Delivers:** Updated `confluence_client.py` with two tested HTML templates (text-only and diagram+component), HTML-escaped LLM text, XML-validated templates in tests, and updated `publish_architecture()` signature
**Implements:** Confluence page template component, graceful degradation carry-forward unchanged
**Avoids:** Pitfall 2 (malformed Confluence HTML across branches)

### Phase 4: Pipeline Orchestration & Approval Flow Integration
**Rationale:** Final assembly — `architecture_pipeline.py` rewrite wires Phases 1-3, plus `webhook.py` idempotency guard and approval-flow regression verification. Must be last because it orchestrates all prior components.
**Delivers:** Full rewrite of `architecture_pipeline.py`; webhook idempotency supersede check; end-to-end approval-flow integration test; removal of `_parse_options` multi-option logic; Jira comment-back with complexity label and Confluence link
**Avoids:** Pitfall 4 (`draft_content` contract breakage), Pitfall 1 (webhook idempotency gap), approval-flow regression

### Phase Ordering Rationale

- Classifier first because every downstream branch (template selection, diagram gating, Jira comment text) is conditional on its output. Building templates before the classifier's output schema is frozen causes rework.
- Diagram service second (parallel to classifier) because it has no classifier dependency — it only needs a fixed component list as input, which a test fixture can provide during development.
- Confluence templates third because both template structures reference the classifier's output shape and the diagram module's return type. Building before those contracts are settled causes rework.
- Pipeline orchestration last because it is the integration layer and can only be correctly implemented once the components it orchestrates have stable interfaces.
- No MCP migration in this milestone. The Confluence REST path is proven and tested. Adding MCP for Confluence would touch `hermes/mcp_client.py` and `hermes/server.py` for a transport change with no new functional requirement.

### Research Flags

Phases with standard patterns (skip additional research):
- **Phase 1 (Complexity Classifier):** Structured LLM classification with low temperature and JSON schema is a documented industry pattern. Rubric design is guided by ADR heuristics and C4 model guidance.
- **Phase 3 (Confluence Publishing):** Confluence storage-format XHTML is documented. The HTML-escape + XML-validate pattern is standard. The diagrams.net viewer URL approach is confirmed plugin-agnostic.
- **Phase 4 (Pipeline Orchestration):** Follows the existing `describe_pipeline`/`assign_pipeline` pattern exactly. No novel integration patterns.

Phases where execution-time validation is advisable:
- **Phase 2 (Diagram Service):** The diagrams.net `?xml=` URL-encoding approach for complex diagrams should be smoke-tested against a real Confluence page early to confirm URL length does not exceed browser/Confluence limits for large diagrams. Fallback to attachment upload is fully documented.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Grounded in direct codebase reading and confirmed drawio-skill GitHub repository behavior. No speculative dependency recommendations. |
| Features | MEDIUM | C4 model guidance (HIGH) and ADR community heuristics (MEDIUM) validate the binary complexity split and doc section choices. Specific threshold values in the rubric need empirical validation against real tickets. |
| Architecture | HIGH | Based on direct reading of 12+ existing source files. Component boundaries, module paths, and call signatures confirmed against live code. |
| Pitfalls | HIGH/MEDIUM | Integration pitfalls (approval-flow contract, webhook idempotency gap, Confluence HTML escaping) are grounded in existing code reading. LLM classification non-determinism and external-tool reliability patterns are well-established industry patterns applied to this architecture. |

**Overall confidence:** HIGH for structural/architectural decisions; MEDIUM for feature boundary judgment calls (exact rubric thresholds, v1.4.x feature timing).

### Gaps to Address

- **Classification rubric threshold values:** Research recommends "2+ distinct components/services mentioned or implied → complex" as the starting threshold, but the right value for this team's Jira ticket vocabulary needs validation against real historical tickets. Plan to adjust after first 10-20 real uses.
- **Diagrams.net URL length limit for complex diagrams:** The `https://app.diagrams.net/?xml=<url-encoded-xml>` approach is confirmed plugin-agnostic but URL-encoded complex diagrams may exceed practical browser limits. Validate in Phase 2 smoke testing; fallback to attachment upload is documented and available.
- **Approval-flow semantics for architecture stage:** The current `approval_detector.py` applies a `describe`-stage approval by calling `put_description` (a Jira write-back). For the architecture stage, "approval" may only mean "acknowledged" with no Jira-side write beyond the original comment. Verify during Phase 4 — may require a small branch in `approval_detector.py`.

## Sources

### Primary (HIGH confidence)
- Direct codebase reading — `backend/routers/webhook.py`, `backend/services/architecture_pipeline.py`, `backend/services/confluence_client.py`, `backend/services/drawio_service.py`, `backend/services/hermes_client.py`, `backend/services/describe_pipeline.py`, `backend/services/assign_pipeline.py`, `backend/services/llm_router.py`, `backend/services/approval_detector.py`, `backend/models/pipeline_state.py`, `hermes/server.py`, `hermes/mcp_client.py`
- Agents365-ai/drawio-skill GitHub repository — confirmed SKILL.md agent skill, not a Python library; XML-only mode in sandboxed environments documented
- C4 model official documentation (c4model.com) — binary complexity split and component-level diagram guidance
- Microsoft Azure Well-Architected Framework ADR guidance — classification rubric heuristics
- Confluence Cloud Storage Format documentation — XHTML-based page body, macro syntax requirements

### Secondary (MEDIUM confidence)
- drawpyo v0.2.5 PyPI/GitHub — confirmed as viable future upgrade path; disk-write workflow confirmed; explicitly not recommended for v1.4
- AWS multi-LLM routing strategies blog — single-call classifier pattern with explicit rubric
- ADR Y-Statements and Nygard-style ADR community resources — doc section choices (summary, rationale, trade-offs/risks together)
- Practitioner blogs on hybrid LLM + rule-based ticket classification — pre-filter pattern rationale

### Tertiary (LOW confidence)
- Confluence Community forum — draw.io macro requiring Marketplace plugin (corroborated by codebase existing approach avoiding it; not testable without a real Confluence instance with the plugin installed)

---
*Research completed: 2026-06-19*
*Ready for roadmap: yes*
