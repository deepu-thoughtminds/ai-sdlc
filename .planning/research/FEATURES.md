# Feature Research

**Domain:** AI SDLC agent — architecture-stage complexity classification + Confluence-published architecture documentation
**Researched:** 2026-06-19
**Confidence:** MEDIUM

This research targets one milestone slice: `@jarvis architecture` complexity classification (small vs. complex/multi-component) and the resulting Confluence doc structure. It assumes the existing `architecture_pipeline.py` (multi-option LLM call + hand-rolled diagram + raw-text Confluence publish) and `confluence_client.py` (async REST client, `publish_architecture()`, storage-format HTML body) as the system being replaced/extended, per `.planning/PROJECT.md`.

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Single LLM call for complexity classification with explicit criteria in the prompt | Industry practice for prompt/task routing favors one classifier call with defined criteria over multi-call pipelines for latency/cost — LLM-based classifiers already add 500-2000ms vs 10-50ms for rules; stacking a second LLM call to "double check" adds cost without reliably improving accuracy at this scale | LOW | Combine classification + recommended architecture generation in one structured LLM call where feasible (one prompt, ask for `complexity: small|complex`, then conditionally-shaped output), or two calls only if combining hurts output quality in testing. Mirrors existing `_build_prompt`/`route_request` pattern already in `architecture_pipeline.py`. |
| Explicit, codeable classification criteria (not vibes) | LLM classifiers are most reliable when given a short rubric, not open-ended judgment — same principle ADR literature uses for "when is an ADR warranted": affects multiple components/modules, has integration points, has viable alternatives/trade-offs worth recording | LOW | Recommended criteria set (ask the LLM to reason over these, return a verdict): (1) number of distinct services/modules/repos mentioned or implied, (2) presence of new or changed integration points (API, queue, webhook, third-party service), (3) data model / schema changes, (4) new external dependencies (new service, new library with infra footprint), (5) whether the change is containable within one existing component's internals. Two or more "yes" signals → complex. |
| Rule-based pre-filter as a cheap first pass (component-count / keyword heuristics) | General pattern in ticket-classification research: use cheap rule-based/keyword signals for clearly reliable splits, reserve LLM judgment for ambiguous cases | LOW | Not a replacement for the LLM call — a cheap guardrail. E.g., if ticket text matches obvious single-file/copy-change keywords ("typo", "rename label", "update config value") with no service names, short-circuit to "small" without even calling the LLM. Otherwise fall through to LLM classification. Optional for MVP; valuable cost-saver later. |
| Exactly one recommended architecture (no options to pick from) | This milestone's explicit replacement goal — current flow's multi-option/awaiting-approval UX is being removed | LOW | Removes `_parse_options` multi-option parsing and the "reply approved [option name]" comment language entirely. Single recommendation only. |
| Two-tier Confluence page structure gated by the complexity decision | Mirrors C4 model's own documentation guidance: Context+Container-level (i.e., narrative/text) is "almost always" sufficient; Component-level diagrams are reserved for complex containers — validates a binary small/complex split as the right level of granularity (not 3+ tiers) | MEDIUM | Small: title, summary, recommended approach (prose), rationale, trade-offs/risks. Complex: same fields plus component list (name, responsibility, tech), integration points/data flow, and at least one diagram. |
| At least one diagram for "complex" classification, zero diagrams for "small" | Diagrams add real maintenance cost; standard practice (C4, ADR-adjacent guidance) is to add diagrams only when the complexity is high enough to justify the upkeep | MEDIUM | Component-level diagram (boxes for each component/service + arrows for integration points), not a 4-level C4 set — a single component/container-style diagram is sufficient per milestone scope. Use real drawio-skill (Agents365-ai/drawio-skill) integration per PROJECT.md decision pending — not the hand-rolled mxGraph generator being removed. |
| Confluence page replaces, doesn't append to, prior architecture content for the same ticket | Avoids stale/duplicate architecture pages cluttering the space when `@jarvis architecture` is re-triggered on the same ticket | LOW-MED | Existing `confluence_client.create_page` always creates new pages; needs either page-lookup-by-title-and-update, or consistent versioned titling. Flag as integration risk against existing `confluence_client.py` (no update/find-by-title method currently). |
| Jira comment with direct Confluence page link posted back | Core UX of the whole platform — "every output linked back to the originating ticket" (PROJECT.md Core Value) | LOW | Reuse existing pattern from `architecture_pipeline.run()` (comment composition + graceful degradation when Confluence publish fails, returning "" URL and a "Confluence publishing unavailable" comment suffix). Keep this graceful-degradation behavior — it's already battle-tested (T-04-03 threat mitigation). |
| Graceful degradation if Confluence publish fails | Same threat mitigation (T-04-03) already implemented; failing the whole pipeline because Confluence is briefly unavailable would block ticket progress | LOW | Carry forward unchanged — catch publish exceptions, post comment without link rather than erroring the whole `@jarvis architecture` trigger. |
| Explicit complexity label visible to the user (in the Confluence page and/or Jira comment) | Builds trust in the agent's judgment call; lets architect override/escalate if the agent under- or over-classified | LOW | E.g., Jira comment: "Classified as: complex (multi-component) — see Confluence for full component breakdown." Cheap to add, high transparency value. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Hybrid rule + LLM classification (cheap heuristic pre-filter, LLM only for ambiguous cases) | Reduces freellmapi/LLM call volume and latency for the common "obviously small" case, directly serving the project's stated LLM-cost constraint | MEDIUM | Aligns with PROJECT.md constraint "freellmapi used for all heavy tasks to minimize API costs." A keyword/component-count pre-filter that skips the LLM call entirely for clear-cut small changes is a genuine cost differentiator versus naive "always call the LLM to classify." |
| Classification rationale surfaced in the doc ("why this was classified as complex") | Most systems hide the classification step; surfacing the reasoning (e.g., "3 services affected: auth-service, billing-service, notification-service; new external dependency: Stripe webhook") builds architect trust and gives them an audit trail | LOW-MED | One extra sentence/section in the LLM output schema — ask the model to return `classification_reason` alongside `complexity` and the architecture content, in the same call. |
| Drawio-skill-generated diagram via real integration (not hand-rolled mxGraph) | The milestone explicitly calls out removing the hand-rolled generator in favor of a real Agents365-ai/drawio-skill integration — this is a genuine upgrade in diagram quality/maintainability over the current MVP-grade plain-text diagram blocks | HIGH | Integration approach (vendor into Python vs. shell out to Claude Code) is explicitly still "decided during research" per PROJECT.md — flag this as needing its own dedicated research pass; not resolved by this features research. |
| Idempotent Confluence page updates (update-in-place on re-trigger) | Differentiator over typical agent tools that just spam new pages; keeps the architecture history clean and the link in Jira always pointing to current content | MEDIUM | Requires extending `confluence_client.py` with a find-or-update-by-title method (Confluence REST supports GET by title + PUT to update an existing page version) — net new client capability, not present today. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Multi-tier complexity scale (e.g., small/medium/large/epic) | Feels more "precise" than a binary split | Adds classification ambiguity, more prompt branches, more doc template variants to maintain, and more chances for the LLM to misclassify at boundary cases — research found no canonical practice using more than a binary "needs deep documentation or not" split (C4's own guidance is binary: usually 2 levels, occasionally a 3rd) | Keep the binary small/complex split this milestone specifies; revisit only if real usage data shows the boundary cases are common and costly. |
| Generating all 4 C4 levels (context, container, component, code) for "complex" tickets | Seems thorough — "more diagrams = better architecture doc" | C4's own model guidance explicitly warns against this: Component and especially Code-level diagrams are only worth the diagram maintenance cost for very complex systems, and Code-level should really be auto-generated from tooling, not LLM-authored prose-to-diagram | One component-level diagram for "complex" tickets; do not attempt context/container/code tiers in this milestone. |
| LLM self-critique / two-pass "generate then re-classify own output" loop | Looks like a quality safeguard | Doubles LLM cost and latency for marginal accuracy gain at this scale; academic routing research treats this as a known cost/accuracy trade-off, not a free win, and the project's explicit constraint is minimizing freellmapi cost | Single well-specified classification+generation call with explicit rubric; add a second pass only if real misclassification rate proves to be a problem in production. |
| Letting the architect override classification via free-text reply parsing | Seems like good UX flexibility, mirrors old "reply approved [option]" pattern | Reintroduces the comment-parsing complexity this milestone is explicitly removing (multi-option approval flow); also creates a second code path needing its own state machine | If override is needed later, make it a structured re-trigger (`@jarvis architecture force-complex`) rather than free-text parsing — defer entirely from this milestone. |
| Storing full classification training/feedback loop (learned classifier) | "Production systems move beyond prompts" — learned classifiers are mentioned as more accurate than rules | Adds infra (labeled data pipeline, model training/serving) wildly disproportionate to this team's scale and freellmapi-only LLM constraint | Single-call LLM classification with a clear rubric is sufficient at this product's current scale; revisit only after volume justifies the investment. |

## Feature Dependencies

```
[Single recommended architecture flow] ──requires──> [Removal of multi-option _parse_options + old comment language]
                                                            (architecture_pipeline.py rewrite, not additive)

[Complexity classification (small|complex)] ──requires──> [Confluence page structure branching]
                                                            (doc template must know complexity before composing body_html)

[Confluence page structure branching] ──requires──> [confluence_client.py publish_architecture() signature change]
                                                            (needs structured sections, not raw architecture_text string)

[Complex-tier diagram generation] ──requires──> [drawio-skill integration decision]
                                                            (vendor-into-Python vs. shell-out-to-Claude-Code — unresolved, separate research)

[Idempotent Confluence updates] ──enhances──> [Confluence page structure branching]
                                                            (not required for MVP; nice differentiator)

[Hybrid rule+LLM pre-filter] ──enhances──> [Complexity classification]
                                                            (optional cost optimization, not required for correctness)

[Jira comment with link] ──requires──> [Confluence publish step]
                                                            (existing graceful-degradation pattern carries forward unchanged)
```

### Dependency Notes

- **Single recommended architecture requires removal of multi-option parsing:** `_parse_options()` and the "Reply 'approved [option name]'" comment text in `architecture_pipeline.py` are tightly coupled to the multi-option flow being replaced. This is a rewrite of `run()`, not an additive change.
- **Confluence page structure branching requires a `publish_architecture()` signature change:** the current client takes one flat `architecture_text` string and a list of `diagram_xmls`. The new flow needs to pass a structured payload (complexity tier + named sections) so `confluence_client.py` can render two distinct HTML templates. This is the clearest concrete dependency on existing code that the roadmap phase must account for.
- **Complex-tier diagram generation requires the drawio-skill integration decision:** PROJECT.md flags this as still undecided ("vendor into Python vs. shell out to Claude Code — decided during research"). This features research does not resolve it; flag for a dedicated technical/feasibility research pass before the diagram-generation phase is planned.
- **Idempotent Confluence updates enhance but don't block the core flow:** can ship v1 with simple "always create new page" (current behavior) and add update-in-place as a fast-follow once the basic complexity-aware flow works end-to-end.
- **Hybrid rule+LLM pre-filter enhances but doesn't block classification correctness:** ship with "always call LLM to classify" first; add the cheap pre-filter once there's usage data showing which tickets are reliably classifiable by keyword/component-count alone.

## MVP Definition

### Launch With (v1.4)

- [ ] `@jarvis architecture` comment trigger (explicit mention, mirrors existing describe/assign trigger pattern) — entry point, no value without it
- [ ] Single LLM call returning `{complexity: small|complex, classification_reason, recommended_architecture: {...}}` with explicit rubric in the prompt (component count, integration points, data model changes, new external dependencies) — core decision the whole milestone hinges on
- [ ] Exactly one recommended architecture in the LLM output (no multi-option parsing) — explicit milestone goal, replaces current behavior
- [ ] Two Confluence page templates gated by complexity: small = summary/rationale/trade-offs prose only; complex = same plus component list + integration points + one diagram — the structural deliverable this milestone is about
- [ ] At least one component-level diagram for "complex" classification only (via real drawio-skill integration, replacing hand-rolled mxGraph generator) — explicit milestone goal
- [ ] `confluence_client.py` updated to accept structured sections instead of one flat text blob — required dependency, not optional
- [ ] Jira comment posted back with Confluence page link and visible complexity label — core "linked back to ticket" value prop, plus transparency into the agent's judgment call
- [ ] Graceful degradation on Confluence publish failure (carry forward existing T-04-03 pattern unchanged) — proven pattern, cheap to keep

### Add After Validation (v1.4.x)

- [ ] Idempotent Confluence page updates (find-by-title + update instead of always-create) — trigger: re-triggering `@jarvis architecture` on the same ticket creates visible page clutter in practice
- [ ] Hybrid rule-based pre-filter before the LLM classification call — trigger: real usage data shows a meaningful share of tickets are obviously small/complex by keyword or component-count alone, justifying the cost savings
- [ ] Structured override re-trigger (e.g., `@jarvis architecture force-complex`) — trigger: architects report the agent's classification is wrong often enough to need a manual override path

### Future Consideration (v2+)

- [ ] Multi-tier complexity scale beyond binary — defer until binary split proves insufficient in practice (current research found no standard practice justifying more than 2 tiers at this stage)
- [ ] Multiple diagram levels (context/container/component) for very large changes — defer until ticket complexity in practice regularly exceeds what one component-level diagram can express
- [ ] Learned/trained complexity classifier — defer until volume justifies the infra investment over single-call LLM classification

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Single LLM classification call with explicit rubric | HIGH | LOW | P1 |
| Single recommended architecture (remove multi-option flow) | HIGH | LOW | P1 |
| Two-tier Confluence page structure | HIGH | MEDIUM | P1 |
| Component-level diagram for complex tier (drawio-skill) | HIGH | HIGH | P1 |
| `confluence_client.py` structured-sections rewrite | HIGH | MEDIUM | P1 |
| Jira comment with link + complexity label | HIGH | LOW | P1 |
| Graceful Confluence-failure degradation (carry forward) | MEDIUM | LOW | P1 |
| Classification rationale surfaced in doc | MEDIUM | LOW | P2 |
| Idempotent Confluence page updates | MEDIUM | MEDIUM | P2 |
| Hybrid rule+LLM pre-filter | MEDIUM | MEDIUM | P2 |
| Structured override re-trigger | LOW | LOW | P3 |
| Multi-tier complexity scale | LOW | HIGH | P3 |
| Learned/trained classifier | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor / Comparable-Pattern Analysis

No direct commercial competitor implements this exact "Jira-comment-triggered single-architecture-recommendation-published-to-Confluence" workflow; comparison instead drawn from adjacent practices:

| Practice Area | How Adjacent Tools/Practices Do It | Our Approach |
|---------|--------------|--------------|
| Task/prompt complexity routing | LLM-based routers (AWS multi-LLM routing, Mindstudio model routers) classify via a single prompt with explicit criteria, escalating to stronger models for harder tasks; rule-based pre-filters used for cheap, unambiguous splits | Single LLM call with explicit rubric (component count, integration points, data model changes, new deps); optional rule-based pre-filter as a v1.4.x enhancement |
| When to document architecture at all | ADR community heuristic: document when a decision affects multiple components, has viable alternatives, or is hard to reverse | Reuse this same heuristic as the small/complex classification rubric — already validates the binary split |
| How much diagramming detail to include | C4 model: Context+Container (prose/high-level) almost always sufficient; Component diagrams reserved for complex containers; Code-level diagrams should be auto-generated, not LLM-authored | Small = prose only (maps to "no diagram needed"); complex = one component-level diagram (maps to C4's Component tier), explicitly not attempting context/container/code tiers |
| ADR/architecture doc sections | Nygard-style ADR: Context, Decision, Consequences (positive and negative together, no separate "Risks" section to hide trade-offs in); Y-statement format compresses context/requirement/decision/alternatives/benefits/drawbacks into one block | Recommended doc sections: Summary, Recommended Approach, Rationale, Trade-offs/Risks (stated together, not hidden) for both tiers; Components + Integration Points + Diagram added only for complex tier |

## Sources

- [Prompt routers and flow engineering: building modular, self-correcting agent systems](https://blog.promptlayer.com/prompt-routers-and-flow-engineering-building-modular-self-correcting-agent-systems/) — MEDIUM confidence (web search, practitioner blog)
- [Multi-LLM routing strategies for generative AI applications on AWS](https://aws.amazon.com/blogs/machine-learning/multi-llm-routing-strategies-for-generative-ai-applications-on-aws/) — MEDIUM-HIGH confidence (vendor engineering blog, AWS)
- [Stop Overthinking: A Survey on Efficient Reasoning for Large Language Models (arXiv)](https://arxiv.org/pdf/2503.16419) — MEDIUM-HIGH confidence (academic survey)
- [TELeR: A General Taxonomy of LLM Prompts for Benchmarking Complex Tasks (arXiv)](https://arxiv.org/pdf/2305.11430) — MEDIUM-HIGH confidence (academic)
- [Architecture Decision Record (ADR) examples, templates, and documentation — GitHub](https://github.com/architecture-decision-record/architecture-decision-record) — MEDIUM confidence (community-curated reference repo)
- [Architecture Decision Record Template: Y-Statements](https://medium.com/olzzio/y-statements-10eb07b5a177) — MEDIUM confidence (practitioner blog, widely cited Y-statement format)
- [Maintain an architecture decision record (ADR) — Microsoft Azure Well-Architected Framework](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record) — HIGH confidence (official vendor documentation)
- [C4 model — Home](https://c4model.com/) — HIGH confidence (official/canonical source for the C4 model)
- [Component diagram — C4 model](https://c4model.com/diagrams/component) — HIGH confidence (official C4 documentation)
- [C4 Model — The Basics (DEV Community)](https://dev.to/rafaeljcamara/c4-model-the-basics-5bk5) — MEDIUM confidence (community explainer, corroborates official docs)
- [Context, Container, Component & Code (visual-c4.com, 2026)](https://visual-c4.com/blog/4-cluster-understanding-c4-model-levels) — MEDIUM confidence (practitioner explainer)
- [Advanced Ticket Triage: Automating Incident Categorization with LLM (Algomox)](https://www.algomox.com/resources/blog/advanced_ticket_triage_llm_incident_categorization/) — MEDIUM confidence (vendor blog)
- [Enhancing Support Ticket Classification: A Hybrid LLM + ML Strategy (Medium)](https://medium.com/@mondal.arup/enhancing-support-ticket-classification-a-hybrid-llm-ml-strategy-for-real-world-accuracy-2df0abcd9e82) — MEDIUM confidence (practitioner blog)
- Existing codebase: `backend/services/architecture_pipeline.py`, `backend/services/confluence_client.py` (read directly — HIGH confidence, ground truth for current system being replaced)

---
*Feature research for: AI SDLC agent architecture-stage complexity classification + Confluence publishing*
*Researched: 2026-06-19*
