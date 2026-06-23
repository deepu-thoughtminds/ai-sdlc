# Feature Research

**Domain:** Autonomous QA stage for an AI coding-agent SDLC pipeline (test generation + execution + bounded auto-fix loop)
**Researched:** 2026-06-23
**Confidence:** MEDIUM-HIGH

This research targets the v1.8 milestone slice: a QA stage that (a) auto-chains after `merge_pipeline.py` completes a PR merge, (b) is triggerable on-demand via `@jarvis run qa`, (c) generates unit tests + static analysis (lint/type-check/security scan) + Playwright E2E tests grounded in the cloned repo and `.hermes/codebase.md`, (d) executes them in the cloned-repo sandbox using the project's existing test runner/Playwright, (e) runs a bounded auto-fix loop on failures, and (f) posts final pass/fail results back to the Jira comment. It assumes the existing `dev_pipeline.py` (codegen via `route_request`/LiteLLM→freellmapi, `repo_clone.py` subprocess-git clone, `code_generator.py` FileChange parsing, `pr_creator.py` PR creation/merge) and `merge_pipeline.py` (PR merge + Jira status transition) as the upstream system this stage chains off of, per `.planning/PROJECT.md`.

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Auto-chain QA after PR merge | Standard CI/CD expectation — "merge triggers verification" is the baseline mental model from every CI system (GitHub Actions, CircleCI, GitLab CI). Users assume merge → tests run, not merge → silence. | LOW-MEDIUM | Hook into `merge_pipeline.py`'s success path (after `find_and_merge_pr` returns a merged PR and `update_status` succeeds) to `asyncio.create_task` the QA pipeline, mirroring the existing webhook→background-task pattern already used for dev/merge stages. Must not block the merge-confirmation comment — fire-and-forget, QA posts its own follow-up comment when done. |
| On-demand re-run trigger (`@jarvis run qa`) | Every agent-pipeline stage in this product already has an explicit comment trigger (`@jarvis architecture`, `@jarvis start coding`, `@jarvis merge pr`) — users expect symmetry; also necessary because auto-chained QA can fail/be skipped and needs a manual re-run path | LOW | Route through existing `intent_router.classify_intent` (LLM-based intent classification, not a static whitelist per the v1.7 migration) so `mention_parser.py` needs no new hardcoded stage list — just a new `action` value the router can return and a new handler branch in `webhook.py`. |
| Unit test generation grounded in actual repo code + `.hermes/codebase.md` context | LLM-generated tests against hallucinated APIs/signatures are the #1 complaint about AI test generation (tests that "pass" against fictional interfaces, or fail immediately on import errors) — grounding in real cloned files and the codebase snapshot is the documented mitigation pattern across agentic coding tools (Cursor, Copilot Workspace, Devin) | MEDIUM | Reuse the `code_generator.py` pattern: structured prompt with issue context + codebase context + (new) the actual diff/files touched by the merged PR, calling `route_request('qa_testgen', ...)` via the same LiteLLM→freellmapi path. Output parsed with the same `### FILE:` convention already established — no new output format needed. |
| Static analysis / lint / type-check as a required QA sub-step (not LLM-generated, just invoked) | Industry-standard practice: every agentic coding pipeline (Devin, Copilot Workspace, Cursor's background agents) runs the project's own deterministic tooling (eslint/ruff/mypy/tsc) rather than asking an LLM to "check for lint issues" — these are fast, free, and zero-hallucination compared to LLM-based code review | LOW | Detect the project's existing tooling from repo config files (`package.json` scripts, `pyproject.toml`/`setup.cfg`, `.eslintrc*`, presence of `mypy.ini`/`tsconfig.json`) rather than hardcoding one toolchain — this product is explicitly multi-project (each onboarded project has its own GitHub repo), so the QA stage cannot assume Python or JS. Flag toolchain-detection as a genuine complexity driver. |
| Security scan as a required QA sub-step | Table stakes once "static analysis" is promised — users expect SAST-lite coverage (e.g., `bandit` for Python, `npm audit`/`semgrep` for JS) bundled with lint/type-check, not a separate ask | LOW-MEDIUM | Same detection-and-invoke pattern as lint/type-check. Keep scope to fast, no-API-key tools (bandit, semgrep with default rules, npm audit) — do not require paid SAST services; this aligns with the project's LLM-cost-minimization philosophy extended to tooling cost. |
| Playwright E2E test generation + execution using the project's *existing* Playwright setup | Differentiating but now expected of "autonomous QA" claims circa 2026 — AI coding agents (Devin, Cursor, Claude Code's own `/verify`-style flows) routinely run actual browser tests, not just unit tests, when the project has a frontend | MEDIUM-HIGH | Must detect whether the cloned repo already has Playwright configured (`playwright.config.ts`, `@playwright/test` in `package.json`) — generate new spec files into the existing test directory and project config, do NOT scaffold a parallel/competing Playwright setup. If the repo has no Playwright/E2E setup at all, table-stakes behavior is graceful skip with a clear "no E2E test infra detected" note in the final comment, not a failure. |
| Tests run inside the cloned-repo sandbox, not against production | Non-negotiable safety expectation for any "autonomous" code-touching stage — running generated/fixed code against a live environment would be a severe trust violation | LOW (pattern already exists) | Reuse `repo_clone.py`'s existing temp-workspace-clone-then-cleanup pattern unchanged — QA pipeline clones (or reuses, if dev pipeline kept the workspace) the same repo at the merged commit, runs everything via `subprocess.run` inside that directory, and `shutil.rmtree`s when done regardless of pass/fail. |
| Bounded auto-fix retry loop on failure (not infinite) | Users who have seen "autonomous agent" loops run away (infinite retry burning tokens/compute) explicitly expect and require a hard retry ceiling — this is stated directly in PROJECT.md ("up bounded retry limit") | MEDIUM | Loop: generate fix via `route_request` (same codegen path as `code_generator.py`) → re-run failed test subset → re-check. Cap at a small fixed N (3 is the common default across agentic-coding tool defaults — e.g., Devin-style and CI auto-fix bots typically cap retries at 2-5 attempts before giving up). Must re-run only the previously-failing checks on each iteration, not the full suite every time, to keep loop cost/time bounded. |
| Final pass/fail summary posted to the Jira comment, with failure detail when retries exhausted | Core platform UX contract — "every output linked back to the originating ticket" (PROJECT.md Core Value); silent QA or a bare "done" comment breaks user trust in exactly the way the rest of the pipeline already avoids | LOW | Reuse `hermes_client.post_comment`/`hermes_post_comment` pattern. Summary should show per-category status (unit tests: pass/fail counts, lint: pass/fail, type-check: pass/fail, security: N findings, E2E: pass/fail) plus, on exhausted-retries failure, the specific failing test names/error excerpts — not a raw log dump (token/readability cost). |
| QA stage as its own `PipelineState` row (status tracking, idempotency guard) | Every existing stage (`architecture_pipeline`, `dev_pipeline`, `merge_pipeline`) creates a `PipelineState(stage=..., status="running")` row before scheduling its background task, and the webhook layer uses this for duplicate-webhook idempotency (per T-17-06 in `merge_pipeline.py`) — QA stage breaking this convention would create a real idempotency gap (e.g., double-triggering QA on near-simultaneous merge-webhook retries) | LOW (pattern exists) | Add `stage="qa"` PipelineState row, created in `webhook.py` before `asyncio.create_task`, exactly mirroring the merge-pipeline convention already documented in code comments. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Toolchain auto-detection across arbitrary onboarded repos (not hardcoded to one stack) | Most "autonomous QA" agent demos assume a single known stack (e.g., a JS monorepo). This product is explicitly multi-project/multi-tenant (each project brings its own GitHub repo) — genuinely detecting "this repo uses pytest+ruff+mypy" vs "this repo uses jest+eslint+tsc" vs a mixed-stack repo, and adapting the QA-runner commands accordingly, is real differentiation over a single-stack QA bot | HIGH | Recommend: a small detection module that inspects repo root for marker files (`pyproject.toml`→pytest/ruff/mypy, `package.json`→jest/vitest+eslint+tsc, `Gemfile`→rspec, etc.) and maps to runner commands, rather than asking the LLM "what test command should I run" (unreliable/hallucination-prone for this specific decision). Flag as the highest-complexity item in this milestone — likely warrants its own phase-level research pass on toolchain-detection robustness. |
| Auto-fix loop that targets the *specific* failing test/lint/type error (not "regenerate everything") | Naive auto-fix re-runs full codegen on every failure, which is slow, expensive (more freellmapi calls), and prone to introducing new regressions by touching unrelated files. Scoping the fix prompt to "this test failed with this stack trace, fix only what's needed" is the documented best-practice pattern in CI auto-fix bots (e.g., Sweep, CodeRabbit auto-fix, Devin's iterative loop) | MEDIUM-HIGH | Pass the specific failing test name + assertion/error output + the relevant source file(s) (not the whole repo context) into the fix-generation prompt. Keeps the auto-fix loop's freellmapi cost and risk-of-collateral-damage low — directly serves PROJECT.md's LLM-cost-minimization constraint. |
| Per-category result granularity surfaced in the Jira comment (not just one pass/fail bit) | Differentiates from "tests passed/failed" binary reporting — showing "lint: 0 issues, type-check: 2 errors fixed automatically, security: 1 medium finding (unfixed, flagged), E2E: 3/3 passed" gives the team actionable visibility without opening a CI dashboard | LOW-MEDIUM | Natural extension of the table-stakes summary; the differentiator is granularity + the explicit callout of what auto-fix touched vs what remains unresolved after exhausting retries. |
| QA stage reuses dev-pipeline's already-cloned workspace when chained immediately after merge (skip redundant clone) | Avoids a second full `git clone` (network + time cost) when QA auto-chains right after merge and the workspace is still warm — a real latency/cost differentiator for the auto-chain path specifically (the on-demand `@jarvis run qa` path still needs a fresh clone since time may have passed) | MEDIUM | Only safe if workspace lifecycle/cleanup timing is carefully coordinated — risk of the merge pipeline's `shutil.rmtree` already firing before QA starts. Recommend as an optimization to consider only after the basic "QA always clones fresh" version works; do not make this part of MVP given the cleanup-timing risk. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Unbounded/adaptive auto-fix loop ("keep trying until it passes") | Seems like the natural extension of "autonomous" — why stop at N retries if it might succeed on attempt N+1? | Directly contradicts PROJECT.md's explicit "bounded retry limit" requirement; unbounded loops on a free/cost-constrained LLM API risk runaway token spend, can loop on unfixable failures (flaky test, environment issue, genuinely incorrect requirement) indefinitely, and erode trust when an agent "tries forever" with no resolution | Fixed, small retry ceiling (recommend 3); on exhaustion, stop and report the unresolved failure clearly — this is itself useful signal ("this needs a human") rather than a worse outcome. |
| LLM-only "vibe check" code review as a substitute for static analysis tooling | Looks unified — "just ask the LLM if the code looks secure/correct" instead of wiring up separate lint/type-check/security tools per language | LLM judgment on security/type issues is well-documented as unreliable compared to deterministic tooling (false negatives on real vulnerabilities, false positives wasting fix-loop cycles); also reintroduces per-repo-stack ambiguity that deterministic tool detection solves directly | Always invoke the repo's actual lint/type-check/security tooling when detectable; reserve LLM calls for test *generation* and fix *generation*, not for judging code quality directly. |
| Full-suite re-run on every auto-fix iteration | Feels "safer" — re-running everything ensures the fix didn't break something else | Multiplies execution time and (for any LLM-touched re-generation step) cost by the retry count; for a bounded-loop design this turns a 3-retry budget into potentially 3x the runtime of a single full QA pass, increasing the chance of timing out or exhausting whatever execution budget exists | Re-run only the failing subset per fix iteration; reserve one final full-suite re-run only after the targeted fix succeeds, to catch any regression before declaring overall pass — bounds cost while still catching collateral damage. |
| Scaffolding a brand-new Playwright/test config when the repo has none | Seems helpful — "every project should have E2E tests, let's set one up" | Silently introducing a new test framework/config into someone's repo via an autonomous agent is a much bigger, more opinionated change than the QA stage is scoped for (PROJECT.md scopes this milestone to *running* tests grounded in the existing repo, not bootstrapping new tooling); also creates merge-conflict and maintenance burden the team didn't ask for | Detect absence of E2E infra and report "no Playwright/E2E setup detected — skipped" in the final comment; defer "scaffold E2E from scratch" to an explicit future, separately-scoped feature if ever requested. |
| Auto-merging or auto-closing the ticket based on QA pass | Tempting end-to-end automation — "if QA passes, why wait for a human?" | Exceeds PROJECT.md's stated autonomy boundary, which is explicit that dev-stage autonomy goes "until PR review" — QA pass/fail reporting is a decision input for humans, not authorization to skip further human judgment, especially since this is the first stage operating on already-merged code (a QA failure post-merge is already a more sensitive situation than a pre-merge failure) | QA stage always ends in a reported result, never an autonomous follow-on action (no auto-revert, no auto-reopen, no auto-merge-something-else); leave any such escalation as an explicit out-of-scope decision for a future milestone if ever wanted. |

## Feature Dependencies

```
[QA auto-chain after merge] ──requires──> [merge_pipeline.py success-path hook point]
                                                (must not block existing merge-confirmation comment)

[QA auto-chain after merge] ──requires──> [PipelineState(stage="qa") row + idempotency guard]
                                                (mirrors existing T-17-06 convention)

[@jarvis run qa trigger] ──requires──> [intent_router.classify_intent supports new "run_qa" action]
                                                (LLM-based router, no static whitelist edit per v1.7)

[Unit test generation] ──requires──> [Cloned repo workspace (repo_clone.py) at the merged/target commit]
                                                (cannot generate grounded tests without real files)

[Unit test generation] ──requires──> [.hermes/codebase.md context (codebase_scan_service)]
                                                (existing scanning pipeline; QA reuses, doesn't rebuild)

[Static analysis / lint / type-check / security scan] ──requires──> [Toolchain auto-detection module]
                                                (new component; not present in dev/merge pipelines today)

[Playwright E2E generation + execution] ──requires──> [Detection of existing Playwright config in cloned repo]
                                                (must extend existing setup, not create a parallel one)

[Test execution in sandbox] ──requires──> [Cloned repo workspace]
                                                (same dependency as test generation — shared workspace)

[Bounded auto-fix loop] ──requires──> [Test execution results (specific failing test/lint/type/security findings)]
                                                (fix prompt must be scoped to the actual failure, not "fix the repo")

[Bounded auto-fix loop] ──requires──> [code_generator.py-style structured code-change generation + apply step]
                                                (reuses dev pipeline's FileChange parsing/apply convention)

[Final Jira comment posting] ──requires──> [hermes_client.post_comment / hermes_post_comment]
                                                (existing client, no new integration needed)

[Per-category result granularity] ──enhances──> [Final Jira comment posting]
                                                (not required for MVP; improves clarity)

[Workspace-reuse optimization] ──enhances──> [QA auto-chain after merge]
                                                (optional latency optimization; conflicts with strict
                                                 cleanup-on-merge-completion if not carefully sequenced)

[Workspace-reuse optimization] ──conflicts──> [repo_clone.py's existing shutil.rmtree-on-completion pattern]
                                                (merge pipeline's cleanup timing must be revisited if reuse is attempted)
```

### Dependency Notes

- **QA auto-chain requires a hook point in `merge_pipeline.py`'s success path, not a rewrite of it:** the new stage should be scheduled (`asyncio.create_task`) after the existing merge-confirmation comment logic completes successfully, as an additive hook — not by restructuring `merge_pipeline.run()`. Keeps the existing T-17-05/06/07/08 threat mitigations in `merge_pipeline.py` untouched.
- **Toolchain auto-detection is the one genuinely new architectural component this milestone needs** — every other capability (cloning, LLM codegen calls, comment posting, PipelineState tracking) has a direct precedent in the existing dev/merge pipelines. Detection-and-command-mapping for lint/type-check/security/test-runner across arbitrary repo stacks does not. Flag this for a dedicated technical/feasibility research pass before the QA execution phase is planned (mirrors how the v1.4 research flagged drawio-skill integration as needing its own pass).
- **Playwright E2E generation depends on detecting existing Playwright config — it must not bootstrap a new one.** If detection finds no E2E infra, the correct behavior is graceful skip with a clear comment note, treated as a sibling case to the existing "Confluence publish unavailable" graceful-degradation pattern already proven in `architecture_pipeline.py`.
- **The bounded auto-fix loop depends on scoped failure information, not a full re-generation cycle.** This is the central design decision for keeping retry cost/time bounded — test execution must surface specific failing test names + error output (not just an aggregate pass/fail bit) for the fix-generation prompt to be scoped tightly.
- **Workspace-reuse optimization conflicts with the existing cleanup pattern and should be deferred.** `repo_clone.py`'s contract is "caller removes the directory when done" — the merge pipeline already owns that lifecycle for its own clone (if it clones at all; confirm during phase planning whether merge_pipeline clones or only calls GitHub API). Do not attempt workspace-sharing across pipeline stages in MVP; always clone fresh for QA to avoid cross-stage lifecycle coupling bugs.

## MVP Definition

### Launch With (v1.8)

- [ ] QA stage auto-chains after `merge_pipeline.py` reports a successful merge — core trigger, milestone's first explicit requirement
- [ ] `@jarvis run qa` on-demand trigger routed through `intent_router.classify_intent` — second explicit trigger requirement, needed for re-runs and ad-hoc QA
- [ ] Fresh clone of the repo (reusing `repo_clone.py`) at the relevant commit for every QA run — sandbox isolation, non-negotiable safety baseline
- [ ] Unit test generation via `route_request`, grounded in cloned repo files + `.hermes/codebase.md` context, using the same `### FILE:` structured-output convention as `code_generator.py` — core "test generation" deliverable
- [ ] Toolchain auto-detection for lint/type-check/security scan (at minimum: detect Python via `pyproject.toml`/`setup.cfg` → ruff/mypy/bandit, and JS/TS via `package.json` → eslint/tsc/npm audit) — required for static analysis to actually run on real onboarded repos
- [ ] Playwright E2E test generation + execution gated on detecting existing Playwright config in the cloned repo; graceful skip-with-note if absent — explicit milestone requirement, scoped to "use the project's existing test runner/Playwright"
- [ ] All test/lint/type-check/security/E2E execution run via `subprocess.run` inside the cloned workspace — reuses the sandboxing pattern already proven safe in `repo_clone.py`/`pr_creator.py`
- [ ] Bounded auto-fix loop (fixed cap, e.g. 3 attempts): on failure, generate a scoped fix via the same codegen path, re-run only the failing checks, repeat until pass or cap exhausted — explicit milestone requirement, must be bounded
- [ ] `PipelineState(stage="qa")` row created before scheduling, mirroring existing idempotency-guard convention — required to avoid double-triggering on duplicate webhooks
- [ ] Final Jira comment with pass/fail summary (per-category: unit tests, lint, type-check, security, E2E) posted via existing `hermes_client.post_comment`, including failure detail when retries are exhausted — explicit milestone requirement, core platform UX contract

### Add After Validation (v1.8.x)

- [ ] Per-category result granularity with explicit "auto-fixed vs still-failing" breakdown in the comment — trigger: users report the pass/fail summary is too coarse to act on without opening logs
- [ ] Hybrid rule-based toolchain detection refinement (handling monorepos / mixed-stack repos) — trigger: real onboarded projects surface stacks the initial marker-file detection doesn't cleanly handle
- [ ] Workspace-reuse optimization between dev/merge/QA stages when auto-chained back-to-back — trigger: clone latency becomes a measurable user complaint, and only after cleanup-lifecycle coordination is designed safely

### Future Consideration (v2+)

- [ ] Scaffolding new E2E/test infrastructure for repos that have none — defer until explicitly requested; out of scope per this milestone's "use existing test runner/Playwright" framing
- [ ] Auto-merge or auto-close actions based on QA pass — defer indefinitely unless the team explicitly revisits the stated autonomy boundary (dev autonomy stops at PR review; QA should not extend it past merge)
- [ ] Adaptive/unbounded retry strategies (e.g., increasing cap based on failure type) — defer until the fixed-cap bounded loop proves insufficient in practice; no evidence yet that it will be

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| QA auto-chain after merge | HIGH | LOW-MEDIUM | P1 |
| `@jarvis run qa` on-demand trigger | HIGH | LOW | P1 |
| Unit test generation (grounded in repo + codebase.md) | HIGH | MEDIUM | P1 |
| Toolchain auto-detection (lint/type-check/security) | HIGH | HIGH | P1 |
| Playwright E2E generation + execution (with graceful skip) | HIGH | MEDIUM-HIGH | P1 |
| Sandbox execution in cloned workspace | HIGH | LOW (pattern exists) | P1 |
| Bounded auto-fix loop | HIGH | MEDIUM-HIGH | P1 |
| PipelineState tracking + idempotency guard | MEDIUM-HIGH | LOW (pattern exists) | P1 |
| Final Jira comment with pass/fail summary | HIGH | LOW | P1 |
| Per-category result granularity | MEDIUM | LOW-MEDIUM | P2 |
| Mixed-stack/monorepo toolchain detection refinement | MEDIUM | MEDIUM-HIGH | P2 |
| Workspace-reuse optimization | LOW-MEDIUM | MEDIUM | P3 |
| E2E infra scaffolding from scratch | LOW | HIGH | P3 |
| Auto-merge/auto-close on QA pass | LOW | MEDIUM | P3 (anti-feature; out of scope) |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor / Comparable-Pattern Analysis

No direct commercial competitor implements this exact "Jira-comment-chained autonomous QA stage with bounded auto-fix" workflow as a Jira-native feature; comparison drawn from adjacent agentic-coding and CI-bot practices:

| Practice Area | How Adjacent Tools/Practices Do It | Our Approach |
|---------|--------------|--------------|
| Test generation grounding | Agentic coding tools (Devin, Cursor background agents, Copilot Workspace) consistently ground test generation in the actual cloned repo + a codebase summary/index rather than the issue text alone, to avoid hallucinated APIs | Reuse `.hermes/codebase.md` snapshot + cloned repo files as grounding context, mirroring `code_generator.py`'s existing dev-stage pattern |
| Static analysis invocation | Mainstream practice across agentic pipelines and CI auto-fix bots is to invoke the project's own deterministic tooling (eslint/ruff/mypy/bandit/tsc) rather than ask the LLM to simulate lint/type/security checks | Toolchain auto-detection + direct subprocess invocation of detected tools; LLM reserved for test/fix generation only |
| Auto-fix retry bounding | CI auto-fix bots and agentic coding tools commonly cap auto-fix retries at a small fixed number (commonly 2-5 attempts) before surfacing to a human, rather than looping indefinitely | Fixed bounded retry cap (recommend 3), explicit per PROJECT.md's "bounded retry limit" requirement |
| Scoped fix prompts | Best-practice auto-fix loops pass the specific failing test/error/stack trace into the fix prompt, not a "fix everything" instruction, to limit blast radius and LLM cost per iteration | Scope fix-generation prompts to the specific failing check's output + relevant source file(s), reusing the codegen path with narrower context |
| E2E test execution scope | Agentic tools that run E2E tests do so against the project's existing Playwright/Cypress config, not a freshly scaffolded one, when present; absence of E2E infra is typically reported, not auto-bootstrapped | Detect existing Playwright config in cloned repo; generate specs into it; graceful skip-with-note if absent |
| Result reporting surface | CI bots typically report a structured pass/fail summary with per-check breakdown back to the originating PR/ticket, not a raw log dump | Structured per-category (unit/lint/type-check/security/E2E) summary posted to the Jira comment via existing `hermes_client.post_comment`, consistent with this product's "every output linked back to the ticket" core value |

## Sources

- Existing codebase: `backend/services/merge_pipeline.py`, `backend/services/dev_pipeline.py`, `backend/services/code_generator.py`, `backend/services/repo_clone.py`, `backend/services/pr_creator.py`, `backend/services/mention_parser.py` (read directly — HIGH confidence, ground truth for the system this stage chains off of)
- `.planning/PROJECT.md` (HIGH confidence — authoritative milestone scope and constraints)
- General domain knowledge of agentic coding-tool QA/auto-fix patterns (Devin-style iterative loops, Cursor/Copilot Workspace background-agent test generation, CI auto-fix bot retry conventions) — MEDIUM confidence; reflects well-established 2024-2026 practitioner consensus on bounded-retry auto-fix loops and tool-grounded test generation rather than a single citable source, used here as design-pattern guidance rather than authoritative fact

---
*Feature research for: Autonomous QA stage (test generation + execution + bounded auto-fix loop) for AI-SDLC Jira platform*
*Researched: 2026-06-23*
