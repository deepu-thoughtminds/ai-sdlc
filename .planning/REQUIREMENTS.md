# Requirements: AI-SDLC Jira

**Defined:** 2026-06-19
**Core Value:** Team members trigger AI-powered SDLC automation directly from Jira comment history, with every output linked back to the originating ticket.

---

## Milestone v1.4: Smart Architecture & Confluence Publishing

Replace Phase 4's multi-option architecture flow with a single complexity-aware architecture flow. When a team member mentions `@jarvis architecture` on a Jira ticket, the agent classifies the requested change (small vs complex), generates exactly one recommended architecture at the appropriate depth, publishes it to Confluence, and posts a comment back to the Jira ticket linking to the page.

---

## Complexity Classification

- [x] **CLASSIFY-01**: Agent makes a single LLM call (temperature=0, structured JSON output) to classify the requested change as "small" or "complex" using an explicit rubric — 2+ distinct components, services, or integration points implies "complex"; result stored in `PipelineState`
- [x] **CLASSIFY-02**: Classification rationale is captured in `PipelineState` and surfaced in the Jira comment alongside the Confluence link (e.g. "Simple change — text architecture" or "Multi-component feature — diagram included")

## Architecture Content Generation

- [x] **ARCHGEN-01**: LLM generates exactly ONE recommended architecture (not 2-3 options to choose from); old `_parse_options()` multi-option logic is removed entirely from `architecture_pipeline.py`
- [x] **ARCHGEN-02**: For "complex" tickets — LLM produces a structured architecture writeup with sections: Summary, Approach, Component Breakdown, Integration Points, Key Decisions, Risks; at least one mxGraph diagram is generated via the enhanced `drawio_service`
- [x] **ARCHGEN-03**: For "simple" tickets — LLM produces a prose architecture writeup with sections: Summary, Approach, Key Decisions, Risks; no diagram is generated
- [x] **ARCHGEN-04**: `drawio_service.py` enhanced in place: generates validated mxGraph XML with directional edges and typed-component placement; XML output is validated (parse check) before embedding; malformed output degrades to text-only path without crashing the pipeline

## Confluence Publishing

- [x] **CONFPUB-01**: `confluence_client.publish_architecture()` updated with two structured HTML templates (text-only branch and diagram+components branch); all LLM-generated text is HTML-escaped before template interpolation; both templates are XML-validated in the test suite
- [x] **CONFPUB-02**: For diagram pages, the Confluence page embeds the raw mxGraph XML in a `<pre class="drawio-xml">` block AND includes a diagrams.net viewer URL (`https://app.diagrams.net/?xml=<url-encoded-xml>`) so architects can open and edit the diagram without the draw.io Confluence Marketplace plugin
- [x] **CONFPUB-03**: Before creating a new page, `confluence_client` searches for an existing page with the same title (`Architecture: {issue_key}`) in the project space; if found, updates the existing page in place instead of creating a duplicate
- [x] **CONFPUB-04**: On Confluence publish failure (any exception), the pipeline degrades gracefully — a Jira comment is still posted with the architecture text inline (no page URL); the pipeline does not crash (existing T-04-03 graceful-degradation pattern carried forward)

## Trigger & Integration

- [x] **ARCHINT-01**: `'architecture'` added to `KNOWN_STAGES` in `mention_parser.py`; a `@jarvis architecture` Jira comment mention correctly routes to the new single-architecture pipeline via the webhook handler
- [x] **ARCHINT-02**: `webhook.py` architecture branch adds an idempotency guard — if an active `PipelineState` for the same ticket at `stage="architecture"` already exists (status not `"failed"`), the duplicate webhook is acknowledged with 200 but the pipeline is not re-triggered
- [x] **ARCHINT-03**: Old multi-option approval prompt removed from `architecture_pipeline.py`; old "Reply 'approved [option name]'" flow removed; the Jira comment posted back contains the architecture summary and Confluence link without asking the team to select an option

---

## Future Requirements (deferred from v1.4)

- Hybrid rule-based pre-filter before LLM classification call (keyword/component-count guardrail for obvious cases, saves tokens) — deferred to v1.4.x
- Override trigger `@jarvis architecture force-complex` / `force-simple` — deferred to v1.4.x
- Auto-chain architecture generation after `@jarvis describe` approval (no explicit mention needed) — deferred to v1.5+

---

## Milestone v1.5: GitHub Dev Pipeline & LLM Intent Routing

Automate the developer stage end-to-end: from reading the published Confluence architecture to cloning the GitHub repo, making autonomous code changes, raising a PR, and merging it. All `@jarvis` mentions are routed through an LLM-based intent classifier instead of a hardcoded keyword whitelist.

---

## GitHub Project Configuration

- [x] **GITHUBCFG-01**: User can enter a `github_repo` owner/repo slug (e.g. `acme/my-app`) in the project onboarding form; the value is stored encrypted in the project DB record alongside existing credentials
- [x] **GITHUBCFG-02**: Project dashboard list displays the configured `github_repo` for each onboarded project

## Developer Coding Pipeline

- [ ] **DEVPIPE-01**: When a Jira comment mentions `@jarvis start coding` (detected via LLM intent router), the agent searches the ticket's comment history for the most recent Confluence architecture page URL (posted by the architecture pipeline) and fetches the page content via the Hermes Confluence MCP client
- [x] **DEVPIPE-02**: Agent clones the project's configured GitHub repo to a temporary workspace directory using the stored (decrypted) GitHub token
- [x] **DEVPIPE-03**: Agent calls freellmapi with the Jira story description, Confluence architecture content, and existing codebase context to generate code changes (file diffs or new files)
- [x] **DEVPIPE-04**: Agent applies the generated changes, commits them to a new branch (`jarvis/issue-{key}`), pushes the branch, and opens a PR against the main branch via the GitHub API
- [ ] **DEVPIPE-05**: Agent posts the PR URL as a new Jira comment on the originating story via Hermes/Jira MCP

## PR Merge

- [x] **PRMERGE-01**: When a Jira comment conveys `merge pr to main branch` intent (detected via LLM intent router), the agent finds the open PR for the current ticket (by branch pattern `jarvis/issue-{key}` or PR title) and merges it to main via the GitHub API using the stored token
- [x] **PRMERGE-02**: After a successful merge, the agent updates the Jira story status via Hermes/Jira MCP and posts the merge commit SHA and status as a new Jira comment

## LLM Intent Routing

- [ ] **INTENT-01**: The `KNOWN_STAGES` whitelist in `mention_parser.py` is replaced by an LLM-powered intent classifier that accepts a free-text `@jarvis` phrase and returns a structured intent object `{action, entities}` — e.g. `{action: "start_coding"}`, `{action: "merge_pr"}`, `{action: "assign", entities: {user: "@alice"}}`
- [ ] **INTENT-02**: When the LLM returns an unrecognized or low-confidence intent, the pipeline posts an informative Jira comment listing valid commands (e.g. "I didn't understand that — try: `@jarvis start coding`, `@jarvis merge pr`, `@jarvis assign @name`") rather than silently dropping the event

---

## Future Requirements (deferred from v1.5)

- QA stage: developer assigns merged PR to QA via comment; agent generates test cases, triggers test runs, reports results back to Jira comment
- Auto-chain: architecture generation auto-triggers after `@jarvis describe` approval without an explicit mention
- PR status polling: agent monitors open PR for CI check results and comments when checks pass/fail

## Out of Scope (v1.5)

- Full CI/CD pipeline integration (triggering builds, watching GitHub Actions) — comment-based async sufficient for v1
- Code review automation (agent reviews PR diffs and comments) — developer reviews manually in v1
- Multi-file conflict resolution during PR merge — happy path only; conflicts surface to developer

---

## Traceability (v1.5)

| REQ-ID | Phase | Plan |
|--------|-------|------|
| INTENT-01 | Phase 14 | TBD |
| INTENT-02 | Phase 14 | TBD |
| GITHUBCFG-01 | Phase 15 | TBD |
| GITHUBCFG-02 | Phase 15 | TBD |
| DEVPIPE-02 | Phase 15 | TBD |
| DEVPIPE-03 | Phase 15 | TBD |
| DEVPIPE-04 | Phase 15 | TBD |
| DEVPIPE-01 | Phase 16 | TBD |
| DEVPIPE-05 | Phase 16 | TBD |
| PRMERGE-01 | Phase 17 | TBD |
| PRMERGE-02 | Phase 17 | TBD |

## Out of Scope (v1.4)

- Multi-tier complexity scale (more than binary small/complex) — no standard practice justifies >2 tiers at current volume
- Multiple C4 diagram levels — one component-level diagram per C4 guidance is sufficient for MVP
- draw.io desktop headless rendering (PNG/SVG export) — requires xvfb + 500MB Electron image; mxGraph XML + diagrams.net URL is plugin-agnostic and sufficient
- drawpyo Python library — disk-write workflow adds complexity with no capability gain at this scope
- Architect approval flow for the new architecture page — v1.4 produces the architecture and posts it; approval/sign-off loop is a v2 concern

---

## Traceability (v1.4)

| REQ-ID | Phase | Plan |
|--------|-------|------|
| CLASSIFY-01 | Phase 10 | TBD |
| CLASSIFY-02 | Phase 10 | TBD |
| ARCHGEN-04 | Phase 11 | TBD |
| CONFPUB-02 | Phase 11 | TBD |
| CONFPUB-01 | Phase 12 | TBD |
| CONFPUB-03 | Phase 12 | TBD |
| CONFPUB-04 | Phase 12 | TBD |
| ARCHGEN-01 | Phase 13 | TBD |
| ARCHGEN-02 | Phase 13 | TBD |
| ARCHGEN-03 | Phase 13 | TBD |
| ARCHINT-01 | Phase 13 | TBD |
| ARCHINT-02 | Phase 13 | TBD |
| ARCHINT-03 | Phase 13 | TBD |
