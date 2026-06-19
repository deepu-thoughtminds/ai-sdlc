# Pitfalls Research

**Domain:** LLM complexity-classification + branching output (diagram/Confluence publishing) added to existing Jira webhook/agent SDLC pipeline
**Researched:** 2026-06-19
**Confidence:** HIGH (codebase-grounded findings on integration points), MEDIUM (LLM classification/drawio-skill general patterns, based on well-established failure modes rather than project-specific incidents)

## Critical Pitfalls

### Pitfall 1: Complexity classification flips between runs for near-identical tickets

**What goes wrong:**
The LLM is asked to decide "text-only vs. diagram+component" for a ticket description. Two architects file structurally similar tickets ("add caching layer to checkout" vs. "add caching layer to search") and get different depth decisions — or worse, the *same* ticket re-run (e.g. after a retry or webhook redelivery) gets a different decision the second time. This is non-deterministic because LLM sampling, prompt-context drift (sprint backlog/codebase context changes between calls), and ambiguous classification boundaries ("is 3 components 'multi-component' or not?") all interact.

**Why it happens:**
- No fixed temperature / determinism setting on the classification call (freellmapi backends vary in default temperature).
- The classification prompt embeds variable context (codebase state via gsd-graphify, sprint backlog) that changes between identical-looking requests.
- The complexity boundary is inherently fuzzy — there's no objective threshold for "small" vs "multi-component" unless the LLM is given an explicit, numeric rubric.
- Architecture pipeline currently has no retry/idempotency guard (webhook redelivery from Jira is common and currently relies on `architecture_pipeline.run` having no dedupe check — confirmed by reading `webhook.py`: the `architecture` stage handler schedules a background task with **no PipelineState pre-check or dedup**, unlike the `describe` stage which explicitly supersedes prior rows before running).

**How to avoid:**
- Make classification a separate, cheap, deterministic-as-possible LLM call (low/zero temperature) with a strict structured rubric (e.g., "count distinct components mentioned or implied; >1 component OR explicit diagram request → diagram+component; else text-only") rather than free-form judgment.
- Force structured output (JSON schema: `{"complexity": "text_only"|"diagram_component", "component_count": int, "reasoning": str}`) so the decision is auditable and testable, not buried in prose.
- Add an idempotency guard before scheduling the architecture background task: check for an existing `PipelineState(stage="architecture", status in ["processing","awaiting_approval"])` row for the ticket and skip/supersede, mirroring the pattern already used in the `describe` stage handler.
- Log the classification decision + reasoning to the PipelineState row (new column or JSON field) so flip-flops are visible in production, not just inferred from user complaints.

**Warning signs:**
- Same ticket re-triggering `@jarvis architecture` produces different page structures across runs.
- Support/architect complaints: "why did this small change get a full diagram" or vice versa.
- Classification reasoning (if logged) shows boundary cases clustering near a threshold with inconsistent verdicts.

**Phase to address:**
Phase implementing the complexity classification step itself (before diagram/Confluence work begins) — get the rubric and idempotency guard right first, since every downstream branch depends on this decision being stable.

---

### Pitfall 2: Confluence page body becomes malformed HTML when content structure varies by branch

**What goes wrong:**
Confluence Cloud's storage format (XHTML-based) is strict — unclosed tags, unescaped `&`/`<`/`>` in LLM-generated text, or macro syntax errors cause the `POST /wiki/rest/api/content` call to fail outright, or worse, **succeed with a corrupted page** (Confluence is sometimes lenient and silently drops malformed nested elements). Today's `architecture_pipeline.py` sidesteps this by wrapping LLM text in `<pre>` tags (confirmed: "T-04-07: LLM output embedded inside `<pre>` tags ... not rendered executable HTML/JS"). The new feature's two branches need *different* page structures (text-only narrative vs. diagram macro + component table), which means two HTML templates instead of one flat `<pre>` block — doubling the surface area for malformed markup, and now the diagram embed (drawio macro or attached image) must be correctly referenced in valid storage-format XML alongside the text.

**Why it happens:**
- Developers test the "happy path" template (e.g., diagram+component) thoroughly but the text-only branch HTML template gets written quickly and undertested since it "looks simpler."
- LLM output is treated as trusted plain text dropped into an HTML template via string interpolation rather than escaped/sanitized, so any stray `<`, `&`, or quote in the LLM's component description breaks the page.
- Confluence storage format macros (e.g., diagram embed via `<ac:structured-macro>`) have specific required child elements; a small mistake (wrong macro name, missing `ac:parameter`) either errors or silently renders blank.
- Two divergent code paths (text-only template vs diagram+component template) means twice the chance one path regresses silently since CI likely only exercises one branch by default.

**How to avoid:**
- HTML-escape all LLM-generated free text (`html.escape()` or equivalent) before interpolating into any Confluence body template, for both branches — don't rely on `<pre>` wrapping alone once you introduce richer structure (tables, macros).
- Build both branch templates as testable functions returning storage-format strings, and unit test each against Confluence's documented storage-format XML schema (or at minimum, validate they parse as well-formed XML via `xml.etree.ElementTree.fromstring` in tests — catches unclosed-tag bugs before hitting the real API).
- Keep the graceful degradation already in place (catch publish exceptions → empty `page_url`, continue to Jira comment) but **also** alert/log distinctly when the failure is a malformed-body error (4xx with validation detail) vs. a transient/network error (5xx/timeout) — these need different remediation and currently the existing `except Exception` swallows the distinction.
- Add a Confluence sandbox/integration test (using a real or mocked Confluence space) that publishes one page per branch and asserts page creation succeeds and renders attachments correctly, not just "no exception raised."

**Warning signs:**
- Confluence pages with visible raw macro syntax or partially rendered content reported by architects.
- `page_url = ""` (the existing graceful-degradation fallback) occurring more often for one branch than the other in logs — a sign that one template is structurally broken.
- 400-series errors from Confluence API with "invalid content" detail in logs, distinguishable from timeouts only if logged with status code.

**Phase to address:**
Phase that implements the structured Confluence publishing (the page-template work), specifically before it's marked done — both branch templates need equal test rigor, not just the "more interesting" diagram branch.

---

### Pitfall 3: External drawio-skill integration is treated as a tested library but behaves like an unreliable subprocess/agent call

**What goes wrong:**
Today's diagram generation (`drawio_service.generate_diagram`) is a hand-rolled, deterministic mxGraph XML generator — it always produces valid output because it's pure Python string templating. Replacing it with the real `Agents365-ai/drawio-skill` (whether vendored into Python or shelled out to Claude Code per the PROJECT.md decision note) introduces a fundamentally different failure profile: it may be an LLM-driven or subprocess-based tool with variable latency, partial/timeout failures, non-zero exit codes, or output that "looks like" valid drawio XML but fails to render (e.g., dangling edge references to nonexistent node IDs, especially likely if the skill is asked to diagram an LLM-described architecture rather than a fixed schema). Teams often integrate such skills assuming "it's a tool, it either works or throws," missing that it can return **plausible-looking but invalid** output that only surfaces as broken when Confluence tries to render the embedded diagram.

**Why it happens:**
- The skill is new to this codebase; there's no existing wrapper, retry, or validation logic the way `drawio_service.py` currently has implicit correctness (it's just template substitution).
- If integration is "shell out to Claude Code" (per the open decision in PROJECT.md), the call inherits subprocess concerns: timeouts, non-JSON/non-XML stdout pollution (log lines mixed with output), working-directory assumptions, and cost/latency that wasn't present in the old hand-rolled generator.
- No validation step is implied by "integrate the skill" — teams often pipe skill output straight into Confluence's diagram macro without checking it's well-formed mxGraph XML first.
- The existing graceful-degradation pattern (catch-all in `architecture_pipeline.py`) was designed for Confluence publish failures, not diagram generation failures — if diagram generation now happens *before* the Confluence publish step in the new design, a partial failure there could either crash the whole pipeline or silently produce a page with no diagram and no explanation, depending on how the new control flow is structured.

**How to avoid:**
- Wrap the drawio-skill call in the same defensive pattern already proven for Confluence: explicit timeout, catch-all exception handling, and a fallback path (e.g., degrade to text-only complexity branch, or publish without the diagram but flag it in the Jira comment) rather than letting a skill failure crash the whole architecture run.
- Validate skill output before using it: parse the returned XML/diagram artifact and confirm it's well-formed and references only declared node IDs, before attempting to embed it in Confluence. Treat the skill as an untrusted external process, not a trusted library call.
- Decide and document the integration mode (vendored-in-process vs. shell-to-Claude-Code) early, because the two have very different failure/observability characteristics — shelling out needs subprocess timeout + stdout/stderr separation handling that vendoring doesn't.
- Add a smoke test that runs the actual skill (not a mock) against a handful of representative architecture descriptions in CI or a pre-merge check, since the existing test suite for the old `drawio_service` almost certainly only tests the deterministic generator and will give false confidence once the generator is swapped.

**Warning signs:**
- Confluence pages with diagram macros that show "unable to render" or blank diagram regions.
- Diagram generation step's latency variance growing much wider than the LLM classification/text-generation steps (a sign it's now bottlenecked by an external process rather than fast template logic).
- Intermittent failures correlated with specific architecture descriptions (e.g., many components, ambiguous relationships) rather than uniform failure — a sign the skill is silently failing on complexity it can't handle, not failing randomly.

**Phase to address:**
The phase that integrates the drawio-skill — should be scoped separately from (and ideally before) the Confluence page-template phase, so diagram reliability is proven with a stub/mocked Confluence target before wiring the two together.

---

### Pitfall 4: Replacing architecture_pipeline.py breaks the approval-detection flow because it depends on exact comment text/state shape, not just behavior

**What goes wrong:**
`approval_detector.py`'s `detect_and_apply_approval` queries `PipelineState` rows filtered by `stage == "architecture"` and `status == "awaiting_approval"`, then takes `arch_row.draft_content` and posts it verbatim (prefixed with the agent marker) as the Jira comment when an architect replies "lgtm"/"approved". It also runs `_parse_developer_from_approval` against the **approval comment**, not the draft — so that part is safe. But the contract that's easy to silently break when rewriting `architecture_pipeline.run`: (a) it must still write a `PipelineState` row with `stage="architecture"`, `status="awaiting_approval"`, and a `draft_content` string that makes sense to post as a standalone Jira comment; (b) it must still return/store something compatible with `award_row.draft_content` being plain text suitable for direct posting — if the new pipeline starts storing structured data (e.g., JSON with separate `text_summary`, `confluence_url`, `complexity`) in `draft_content` instead of a flat string, the approval flow will post raw JSON into the Jira comment without any code change being obviously "wrong" until QA notices garbled output.

**Why it happens:**
- `draft_content` is a single text column with an implicit contract ("ready-to-post Jira comment body") that isn't enforced by any schema or test on the producer side — only the consumer (`approval_detector`) assumes the shape.
- When a pipeline stage is rewritten, it's natural to restructure internal data (e.g., to carry complexity + Confluence URL + diagram metadata together) without re-checking what the approval flow expects to find in that exact field.
- There's no contract test today asserting "architecture_pipeline.run always leaves a PipelineState row whose draft_content, when posted verbatim to Jira, is well-formed" — this would only be caught by an integration test exercising the full describe→approve loop for architecture, which may not exist yet (worth confirming during phase execution).
- The `AGENT_BODY_MARKER`/`AGENT_COMMENT_PREFIX` self-comment-loop guard and `_parse_developer_from_approval`'s `@mention` regex both depend on the **shape of comments the agent posts and the architect's reply**, not on `architecture_pipeline.py` internals — so these are at lower risk, but if the new feature changes how the agent's own comments are formatted (e.g., adds new markdown the regex doesn't expect) there's a secondary risk to mention-parsing on the *next* turn (e.g., assigning a developer from the approval comment).

**How to avoid:**
- Treat `draft_content` as a stable public contract: whatever the new architecture pipeline produces, ensure the value persisted to `PipelineState.draft_content` is the literal text to be posted to Jira (a rendered summary line + Confluence link), not a JSON blob or partial template — keep any structured complexity/diagram metadata in separate fields or a new JSON column if needed, never inside `draft_content`.
- Add (or verify there exists) an integration test that runs the new `architecture_pipeline.run`, then calls `approval_detector.detect_and_apply_approval` against a synthetic "lgtm" comment, and asserts the resulting Jira comment post call receives well-formed text — this closes the gap between unit-testing the pipeline in isolation and the consumer's actual usage.
- Audit `webhook.py`'s architecture branch for the missing idempotency/supersede logic (see Pitfall 1) while doing this rewrite, since this is the natural place to fix it without extra ticket overhead, but flag it explicitly rather than silently changing behavior as a side effect of the rewrite.
- If the new feature changes the agent's posted-comment markdown structure (e.g., richer formatting with the complexity decision shown inline), grep for and re-verify `_parse_developer_from_approval`'s `@([\w.\-]+)` regex still doesn't false-positive on any new text patterns the agent itself might introduce (e.g., if the comment now references a Confluence space like "@PROJ" anywhere it could be mistaken for a mention) before merging.

**Warning signs:**
- Jira comments posted after approval contain raw JSON, Python repr output, or template placeholders instead of readable text.
- `assign_pipeline.run` triggered unexpectedly (false-positive developer mention extraction) after an architecture approval, post-rewrite.
- Architecture approval flow integration tests (if added) fail only after the pipeline rewrite lands, despite the pipeline's own unit tests passing — a sign the contract broke without anyone touching `approval_detector.py`.

**Phase to address:**
The phase that swaps in the new architecture pipeline implementation — must include an explicit "approval flow regression check" as an acceptance criterion, not just "new pipeline generates correct output."

---

### Pitfall 5: Testing the classification branch only with hand-picked "obviously simple" and "obviously complex" examples, never the ambiguous middle

**What goes wrong:**
Test suites for LLM-classified branching logic tend to converge on a small set of clearly-distinguishable fixtures ("add a logging statement" → text-only; "build a multi-service event-driven order pipeline" → diagram+component) because they're easy to write and obviously correct. This gives false confidence — the cases that actually cause production pain are the boundary cases (a 2-component change, a refactor that touches 3 files but isn't really "architectural"), and those never get covered. Combined with Pitfall 1's inherent non-determinism, this means CI can be green while real usage flips unpredictably on the tickets architects actually file.

**Why it happens:**
- Non-deterministic LLM output is hard to assert on with standard equality-based test patterns, so test authors gravitate toward inputs where the "obviously correct" answer is unambiguous enough that minor sampling variance won't change the verdict.
- There's pressure to keep tests fast/cheap, so testing many boundary variations against a real LLM call is deprioritized in favor of a couple of golden-path assertions, possibly mocked entirely.
- No structured rubric (see Pitfall 1's fix) means there isn't even a clear definition of where the boundary *is*, so it's hard to write a deliberate boundary-case test without first deciding the rubric.

**How to avoid:**
- Once a structured rubric exists (e.g., component-count threshold), write the test suite around the **boundary**, not just the extremes: test at threshold-1, threshold, threshold+1 component counts, and assert the rubric-driven logic (not the LLM call itself) makes the correct branch decision — i.e., split "parse LLM's structured judgment into a branch enum" (pure, deterministic, fully unit-testable) from "ask the LLM to judge" (inherently fuzzy, tested separately with looser assertions or snapshot/regression tracking).
- For the LLM-call portion itself, use a small fixed eval set (10-20 representative real-world-style tickets) run periodically (not necessarily on every CI run) and track classification consistency over time/across model versions — this catches "the LLM provider silently changed default behavior" drift that a single CI run never would.
- Mock the LLM response in unit tests for the branching/templating logic so that logic is tested deterministically regardless of LLM variance, then have a smaller number of real-LLM-backed tests purely to sanity-check the prompt/rubric still gets reasonable classifications.

**Warning signs:**
- Test suite has high coverage numbers but bug reports mention "the agent classified this wrong" for tickets that don't look like edge cases to the reporter.
- Classification eval set (if added) shows decision flips across consecutive runs/model updates without any code change.
- All classification tests use mocked/stubbed LLM responses with no real-call sanity check at all (overcorrection risk in the other direction — never validating the actual prompt against a real model).

**Phase to address:**
The phase implementing complexity classification — define the rubric and the boundary-focused test plan together, before building out the branching pipeline logic that depends on it.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|------------------|
| Store classification decision only as a string inside `draft_content`/comment text, not as a structured DB field | Faster to ship, no migration needed | Can't query/report "how often did we pick diagram vs text-only," can't debug flip-flops without re-reading old comments | Never for MVP — add a `complexity` column to PipelineState or a sibling table; this is cheap to do upfront |
| Skip drawio-skill output validation, trust it's always well-formed | Faster integration, less code | Malformed diagrams silently published to Confluence, discovered by architects not by tests | Only acceptable in a throwaway spike, never in the milestone's shipped phase |
| Reuse `draft_content` text column for richer structured output (JSON) instead of adding new columns | No migration, no schema change | Breaks the approval flow's "post verbatim" contract (Pitfall 4) | Never — add columns/fields instead |
| Catch-all `except Exception` around both diagram generation and Confluence publish, collapsing all failure types into one degraded fallback | Simple, matches existing T-04-03 pattern | Can't distinguish "Confluence is down" from "we generated garbage" from "skill is overloaded" in logs/metrics | Acceptable short-term if exception type/message is still logged distinctly; not acceptable if logging is also generic |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|-------------------|
| Confluence Cloud storage format | Assuming any valid HTML snippet is valid Confluence storage-format XHTML; not escaping LLM text before interpolation | HTML-escape all dynamic text; validate templates are well-formed XML in tests; use Confluence's documented macro schemas exactly (e.g. drawio/image macros) |
| drawio-skill (external tool/agent) | Treating it as a deterministic library call with no failure mode beyond exceptions | Wrap with timeout + output validation (parse/verify XML structure) before using the result; have an explicit fallback (degrade complexity branch or omit diagram) |
| PipelineState (`stage="architecture"`) row reuse across rewrite | Changing the shape/semantics of `draft_content` without checking `approval_detector.py`'s consumption contract | Treat `draft_content` as a stable "ready to post" text contract; add new columns for structured metadata instead of repurposing it |
| Jira webhook redelivery | No idempotency check before scheduling the architecture background task (`asyncio.create_task` fires unconditionally on every matching webhook) | Add a pre-check/supersede of existing `awaiting_approval`/`processing` PipelineState rows for the ticket+stage, mirroring the `describe` stage's existing pattern |
| freellmapi classification call | Assuming default sampling temperature is deterministic/low across different backing models | Explicitly set temperature low (or 0) and request structured JSON output for the classification sub-call specifically, even if other LLM calls in the pipeline use higher temperature for creative text generation |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|------------------|
| Sequential LLM calls (classify → generate text/components → generate diagram → publish) all in one background task with no intermediate persistence | A failure late in the chain (e.g., Confluence publish) discards all earlier LLM work; user has to retrigger the entire expensive chain | Persist intermediate results (classification decision, generated content) to PipelineState incrementally so retries don't redo LLM calls unnecessarily | Becomes painful once diagram generation (drawio-skill, possibly subprocess-based) adds meaningful latency/cost per call — visible once a few users hit transient Confluence failures and have to "redo everything" |
| drawio-skill invoked synchronously inside the same background task as everything else | Single ticket's architecture run blocks on an external tool's latency; webhook handler already returns immediately (good), but if diagram gen is slow/flaky it delays the Jira comment significantly | Keep the diagram step isolated with its own timeout distinct from the overall task; consider posting a partial "still generating diagram" update or just bounding total pipeline time | Noticeable once the skill's latency variance is much higher than the old deterministic generator's near-zero latency |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Interpolating LLM-generated architecture text (which may itself echo parts of the ticket description, potentially containing user-supplied content) directly into Confluence HTML without escaping | Stored XSS-like injection into Confluence pages if a ticket description contains HTML/script-like text that the LLM echoes verbatim | Always HTML-escape LLM output before Confluence template interpolation — extends the existing `<pre>`-wrapping mitigation (T-04-07) to the new richer templates, don't let it lapse when the format gets more complex |
| Passing raw ticket description/comment text to the drawio-skill subprocess (if shelled out) without sanitizing for shell metacharacters | Command injection risk if the skill invocation builds a shell command string from ticket content rather than using argument arrays | Pass content via stdin/file/argv array, never string-interpolated shell command, regardless of which integration mode (vendored vs. shell-out) is chosen |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Architect can't see *why* the agent chose text-only vs diagram+component | Erodes trust; architect can't correct a wrong classification without re-filing the ticket differently | Include a one-line "Complexity assessed as X because Y" rationale in the Jira comment, sourced from the structured classification output (see Pitfall 1) |
| No way to override/re-request the other depth if the agent guessed wrong | Architect stuck with whatever depth was chosen; has to manually ask again with different wording and hope for a different result | Support an explicit override mention (e.g., `@jarvis architecture --diagram` or similar) so users aren't purely at the mercy of classification |

## "Looks Done But Isn't" Checklist

- [ ] **Complexity classification:** Often missing a structured/auditable rubric — verify the decision and reasoning are persisted (not just acted on silently) and that boundary cases were explicitly tested, not just obvious extremes.
- [ ] **Confluence templates (both branches):** Often missing escaping/validation for the *less-tested* branch — verify both text-only and diagram+component templates have equal test coverage and pass well-formed-XML checks, not just "no exception in happy path."
- [ ] **drawio-skill integration:** Often missing output validation — verify generated diagram artifacts are checked for structural validity before being embedded in Confluence, not assumed correct because "the skill ran without error."
- [ ] **Architecture approval flow after rewrite:** Often missing an end-to-end regression test — verify `architecture_pipeline.run` → `PipelineState.draft_content` → `approval_detector.detect_and_apply_approval` → posted Jira comment text is exercised together, not just the new pipeline in isolation.
- [ ] **Webhook idempotency for architecture stage:** Often missing entirely (confirmed absent in current code) — verify a redelivered/duplicate `@jarvis architecture` webhook doesn't spawn two concurrent background tasks racing to write PipelineState rows.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|------------------|
| Classification flip-flopping in production | LOW | Add the structured rubric + low-temperature setting retroactively; backfill a `complexity` column read from historical comment text if needed for analysis, otherwise just fix forward |
| Malformed Confluence pages already published | MEDIUM | Add HTML-escaping + XML-validation tests, then re-run publish for affected tickets (or manually fix pages); requires identifying affected tickets via logs of `page_url != ""` combined with error reports |
| draft_content contract broken (approval posts garbled text) | MEDIUM | Patch `architecture_pipeline.run` to flatten structured data back into a plain-text `draft_content`; add the missing contract test so it can't regress again; any already-posted garbled Jira comments need manual correction (no automated fix possible after the fact) |
| Duplicate architecture pipeline runs from missing idempotency guard | LOW | Add the supersede-on-new-trigger logic (same pattern as `describe` stage); existing duplicate PipelineState rows can be cleaned up with a one-off query marking older `awaiting_approval` rows as `superseded` |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|---------------|
| Classification inconsistency / non-determinism | Complexity classification phase (first) | Boundary-case test suite passes consistently across repeated runs; classification reasoning is logged and queryable |
| Confluence malformed HTML across branches | Confluence page-template phase | Both branch templates pass XML well-formedness tests; integration test publishes a real/sandboxed page per branch successfully |
| drawio-skill reliability | Drawio-skill integration phase (scoped separately, ideally before or parallel to Confluence template phase with a stub target) | Output validation step exists and is tested with at least one deliberately malformed skill response fixture; smoke test against the real skill passes |
| Approval-flow contract breakage | Architecture pipeline rewrite/cutover phase | End-to-end test: new pipeline run → simulated "lgtm" comment → assert posted Jira comment text is clean, human-readable, and contains the Confluence link |
| Missing webhook idempotency for architecture stage | Architecture pipeline rewrite/cutover phase (same phase as approval-flow fix, low incremental cost) | Test that two rapid-fire identical webhooks for the same ticket result in only one active PipelineState row, mirroring existing `describe`-stage supersede test if one exists |
| Untested boundary/ambiguous classification cases | Complexity classification phase | Test fixtures explicitly include near-threshold examples, not just obvious extremes; CI assertion is on the deterministic rubric-parsing logic, with a separate periodic eval for the LLM call itself |

## Sources

- Direct codebase inspection: `/home/deepu/thoughtminds_projects/ai-sdlc-jira/backend/services/architecture_pipeline.py`, `approval_detector.py`, `confluence_client.py`, `mention_parser.py`, `routers/webhook.py` (HIGH confidence — these are read directly from the existing implementation and its documented threat mitigations T-03-10, T-03-14, T-04-01, T-04-03, T-04-06, T-04-07, T-04-08).
- `.planning/PROJECT.md` milestone definition for v1.4 Smart Architecture & Confluence Publishing (HIGH confidence — primary source for scope).
- General LLM-classification non-determinism and structured-output best practices, Confluence Cloud storage-format XHTML strictness, and external-tool/subprocess integration reliability patterns — synthesized from well-established software engineering practice for LLM-driven branching pipelines and REST-based wiki publishing (MEDIUM confidence — no project-specific incident reports exist yet since this is a pre-implementation milestone; these are documented industry failure modes applied to this specific architecture).

---
*Pitfalls research for: LLM complexity-branching architecture/Confluence publishing feature in AI-SDLC Jira*
*Researched: 2026-06-19*
