# Project Research Summary

**Project:** AI-SDLC Jira — v1.8 Autonomous QA Stage
**Domain:** Autonomous QA stage (test generation + sandboxed execution + bounded auto-fix loop) for Jira-comment-driven AI SDLC pipeline
**Researched:** 2026-06-23
**Confidence:** MEDIUM-HIGH

## Executive Summary

The v1.8 milestone adds a QA stage to an existing FastAPI + Next.js + Docker Compose agentic SDLC platform. The QA stage auto-chains after `merge_pipeline.py` completes a PR merge and is also triggerable on-demand via `@jarvis run qa` in Jira comments. It generates unit tests, runs static analysis (lint/type-check/security), generates and runs Playwright E2E tests when the target repo has existing Playwright infra, and applies a bounded auto-fix loop when failures are found — posting the full result back to the originating Jira ticket. Every capability integrates into existing patterns (`repo_clone.py`, `code_generator.py`, `pr_creator.py`, `hermes_client.post_comment`) rather than inventing parallel infrastructure.

The recommended approach builds four new modules (`qa_pipeline.py`, `test_generator.py`, `test_executor.py`, `auto_fix_loop.py`) in a specific dependency order: sandbox/execution infra first, then test generation, then auto-fix loop, then trigger wiring and E2E. The stack extends minimally: `docker` Python SDK (`7.1.x`) and `tenacity` (`9.0.x`) are the only new backend dependencies. A dedicated `qa-sandbox` Docker image (based on `mcr.microsoft.com/playwright:v1.49.0-noble`) houses all QA tooling (ruff, bandit, mypy, Playwright browsers) so the main backend image stays clean.

The biggest risk cluster is execution isolation: the existing dev pipeline already runs LLM-issued `Bash` commands inside the backend container with no additional boundary, and QA introduces a second, more dangerous risk — executing the target repo's own arbitrary test/build scripts verbatim. This must be addressed first, in Phase 23, before test generation or auto-fix is built. Three additional critical risks are tightly coupled: the auto-fix loop must be bounded by both an iteration count AND a wall-clock timeout AND a non-progress detector; auto-fix commits must always open a new PR (never push to main); and the two QA trigger paths (auto-chain + comment) must share a single idempotency-checked scheduler to prevent concurrent duplicate runs.

## Key Findings

### Recommended Stack

The QA stage reuses the existing LiteLLM→freellmapi pipeline for test and fix generation (via `claude-agent-sdk==0.2.107` already pinned), `repo_clone.py` for workspace management, and `hermes_client.post_comment` for result reporting. New dependencies are minimal: `docker>=7.1.0` (Python SDK for spawning the ephemeral QA sandbox container) and `tenacity>=9.0.0` (structured bounded retry with backoff). All QA tooling (ruff, bandit, mypy, Playwright + browser binaries, semgrep) lives in a new `backend/qa-sandbox/Dockerfile` based on `mcr.microsoft.com/playwright:v1.49.0-noble` — keeping the main backend image unchanged. The Playwright package version and the Docker base image tag must be pinned to the same minor version (currently `1.49.x`) — mismatched browser binary vs. package version is the most common Playwright-in-Docker failure mode.

**Core technologies:**
- `claude-agent-sdk==0.2.107` (existing pin): LLM-driven test and fix generation — reuse exactly as `agentic_coder.py` does, via LiteLLM→freellmapi
- `docker>=7.1.0,<8.0.0`: spawn ephemeral sibling container per QA run with `--network=none`, memory, CPU, and pids limits — the minimum viable sandbox for executing arbitrary repo test scripts
- `tenacity>=9.0.0,<10.0.0`: structured bounded auto-fix retry with iteration cap, backoff, and logging — cleaner and more testable than a hand-rolled loop
- `mcr.microsoft.com/playwright:v1.49.0-noble` (QA sandbox base image): pre-ships Playwright browser binaries, eliminating per-run Chromium downloads; pinned minor version matches `playwright` Python package

### Expected Features

The v1.8 scope is fully defined and prioritized. Every P1 feature ships in this milestone; P2/P3 deferred.

**Must have (table stakes — P1):**
- QA auto-chains after `merge_pipeline.py` reports a successful PR merge (fire-and-forget, never blocks the merge comment)
- `@jarvis run qa` on-demand trigger routed through `intent_router.classify_intent` (LLM-based router, no static whitelist edit)
- Fresh `repo_clone.py` clone for every QA run (sandbox isolation baseline — never reuse merge pipeline's workspace)
- Unit test generation via `route_request`, grounded in cloned repo files + `.hermes/codebase.md`, using the existing `### FILE:` output convention
- Toolchain auto-detection: Python (`pyproject.toml`/`setup.cfg` → ruff/mypy/bandit) and JS/TS (`package.json` → eslint/tsc/npm audit)
- Playwright E2E test generation + execution gated on detecting existing `playwright.config.*` in the cloned repo; graceful skip-with-note if absent
- All test/lint/security execution via `subprocess.run` inside the cloned workspace (isolated sandbox, not LLM `Bash` tool calls)
- Bounded auto-fix loop: fixed cap (3 attempts), scoped fix prompts (specific failing test + error output), re-run failing subset only
- `PipelineState(stage="qa")` row with idempotency guard before scheduling (mirrors existing `architecture`/`merge_pr` pattern)
- Final Jira comment with per-category pass/fail summary (unit tests, lint, type-check, security, E2E) via `hermes_client.post_comment`

**Should have (P2 — add after v1.8 validation):**
- Per-category result granularity with explicit "auto-fixed vs still-failing" breakdown
- Mixed-stack/monorepo toolchain detection refinement
- "QA in progress, attempt N of M" intermediate comment updates

**Defer (v2+):**
- Scaffolding new E2E/Playwright infra from scratch for repos that have none
- Auto-merge or auto-close actions based on QA pass
- Adaptive/unbounded retry strategies
- Workspace-reuse optimization between dev/merge/QA stages when auto-chained

### Architecture Approach

The QA stage integrates as a new pipeline module that orchestrates four new backend modules while touching five existing ones minimally. The data flow is: trigger (webhook or merge_pipeline) → `qa_pipeline.py` (clone → generate → execute → fix loop → post result). The two trigger paths must both route through a single shared scheduling helper with one idempotency check, to prevent concurrent duplicate QA runs for the same ticket — a gap specific to this milestone since every prior stage had only one trigger.

**Major components:**
1. `qa_pipeline.py` (NEW) — top-level orchestrator: clone, generate, execute, fix-loop, post result; handles both trigger paths
2. `test_generator.py` (NEW) — LLM test generation via freellmapi; reuses `### FILE:` output convention from `code_generator.py`
3. `test_executor.py` (NEW) — toolchain detection + subprocess execution + `TestResult` structured output; Playwright sandbox invocation
4. `auto_fix_loop.py` (NEW) — bounded retry (iteration cap + wall-clock timeout + non-progress detection); applies fixes via `code_generator.apply_code_changes()`; opens new PRs via `pr_creator.py`
5. `webhook.py` (MODIFY) — add `run_qa` intent route + shared scheduling helper with idempotency guard
6. `merge_pipeline.py` (MODIFY) — add auto-chain call at success path using the same shared scheduling helper
7. `mention_parser.py` (MODIFY) — add `run_qa` to recognized intents
8. `PipelineState` model (MODIFY) — add `qa_attempt` tracking field

### Critical Pitfalls

1. **Unsandboxed test execution** — Reusing `agentic_coder.py`'s `Bash`-tool pattern for QA test execution runs the target repo's arbitrary test/build scripts inside the live backend container with full network access to sibling services. Prevention: test runner invocation must be a controlled `subprocess.run` from orchestrator code via the Docker SDK sandbox; LLM `Bash` tool access is for generating test files only. Sandbox must use `--network=none` or a network that cannot reach `litellm`, `mcp-atlassian`, or `freellmapi` on `ai-sdlc-net`.

2. **Unbounded / non-converging auto-fix loop** — An iteration counter alone is insufficient. The loop must also enforce a combined wall-clock timeout and detect non-progress (same test fails with materially the same error after a fix attempt, meaning stop early rather than burning the full retry budget). Retry count must be persisted in `PipelineState` so a mid-loop crash doesn't restart from zero.

3. **Auto-fix commits pushed directly to `main`** — The project's autonomy boundary is explicit: codegen creates PRs, humans merge. Auto-fix commits must use `pr_creator.py` to open a new branch (`jarvis/qa-fix-{issue_key}`) + PR against `main`, never push directly. This is a hard constraint.

4. **Flaky Playwright E2E failures treated as real defects** — Container-induced Playwright failures (insufficient `/dev/shm`, zombie processes, CPU throttling races) look identical to genuine assertion failures from the test runner's exit code alone. Prevention: retry the exact same failing test once without code changes before invoking auto-fix; classify pass-on-retry as "flaky, reported but not fixed." Playwright sandbox must be explicitly sized with `--shm-size=1GB+` and `--init`.

5. **QA trigger race/duplication** — Both auto-chain and on-demand comment triggers schedule a `PipelineState(stage="qa")` background task. If they use separate scheduling code paths, a merge + simultaneous `@jarvis run qa` comment can race, creating two concurrent QA runs with conflicting auto-fix branches and duplicate Jira comments. Prevention: route both paths through one shared scheduling helper with the existing `status.in_(["running"])` pre-check.

6. **Stale codebase context across auto-fix iterations** — Computing `directory_tree`/codebase context once at QA-run start and reusing it for every retry (matching `dev_pipeline.py`'s one-shot pattern) causes fix attempt N+1 to contradict or duplicate fix attempt N's changes. Prevention: re-derive cheap local context (fast `git diff --stat` + directory walk, not a full `codebase_scan_service.run()`) before each retry, and pass the prior attempt's diff explicitly into the next fix prompt.

## Implications for Roadmap

Research maps directly onto four sequential phases (Phase 23–26 per the architecture recommendation). The ordering is determined by hard dependency: sandbox execution must exist before test generation; test generation must exist before the auto-fix loop; both must exist before trigger wiring is meaningful to test end-to-end.

### Phase 23: QA Foundation and Sandbox Execution

**Rationale:** Pitfall 1 (unsandboxed execution) is the highest-priority design decision — it must be resolved before any test execution code exists, because test generation and the auto-fix loop both compound the blast radius of an unsandboxed executor. Building the sandbox first forces the right architectural boundary (LLM generates files; orchestrator runs them) before shortcuts like "just extend `agentic_coder.py`" become tempting.
**Delivers:** `qa_pipeline.py` skeleton, `test_executor.py` (toolchain detection + subprocess execution with resource limits), `backend/qa-sandbox/Dockerfile`, Docker SDK integration, `PipelineState(stage="qa")` with `qa_attempt` field, flaky-test retry-without-fix check, static analysis only (no LLM calls yet — validates sandbox and toolchain detection independently)
**Addresses:** Toolchain auto-detection (P1), sandbox execution (P1), PipelineState tracking (P1)
**Avoids:** Pitfall 1 (unsandboxed execution), Pitfall 4 (flaky test handling — add retry-without-fix before auto-fix loop exists)

### Phase 24: Test Generation

**Rationale:** With the sandbox executor in place, test generation is additive and low-risk — it generates files that the already-proven executor runs. A standalone test generation + execution pass (generate → execute → post comment, no retry) validates the end-to-end LLM→freellmapi→files→executor→comment flow before adding retry complexity.
**Delivers:** `test_generator.py` (unit test generation + Playwright E2E generation via freellmapi, using `### FILE:` convention), write-generated-tests-to-workspace step, first full end-to-end QA pass (generate + execute + post Jira comment)
**Uses:** `claude-agent-sdk`, LiteLLM→freellmapi, `.hermes/codebase.md` context reuse, `### FILE:` output parsing from `code_generator.py`
**Implements:** `test_generator.py` architecture component; completes `qa_pipeline.py` core flow
**Avoids:** Hallucinated-API test generation (prompts grounded in cloned repo files + codebase.md + PR diff)

### Phase 25: Bounded Auto-Fix Loop

**Rationale:** The auto-fix loop is the highest-complexity feature with the most pitfall surface (Pitfalls 2, 3, 6). Isolating it to its own phase after the sandbox executor and test generator exist means each retry iteration can be validated against real test output, making non-progress detection and context-freshness logic testable independently.
**Delivers:** `auto_fix_loop.py` (iteration cap, wall-clock timeout, non-progress/convergence detection, incremental context refresh per iteration, new PR creation via `pr_creator.py` for fix commits)
**Uses:** `tenacity` for bounded retry, `code_generator.apply_code_changes()` for applying fixes, `pr_creator.py` for `jarvis/qa-fix-{issue_key}` branch + PR
**Avoids:** Pitfall 2 (unbounded loop), Pitfall 3 (stale context), Pitfall 6 (direct push to main)

### Phase 26: E2E Integration and Trigger Wiring

**Rationale:** E2E Playwright execution and the two-trigger orchestration wiring are the most user-visible changes, but both depend on the execution pipeline being solid (Phases 23–25). Doing trigger wiring last means idempotency logic can be tested against a working QA pipeline rather than a skeleton.
**Delivers:** Playwright E2E test generation + execution with graceful skip when Playwright config absent; `@jarvis run qa` mention trigger via `intent_router.classify_intent`; auto-chain hook in `merge_pipeline.py`; shared scheduling helper with single idempotency guard for both trigger paths; per-category result labeling in Jira comments ("Auto-triggered after merge" vs. "Triggered by @jarvis run qa")
**Uses:** Playwright sandbox image, Docker Compose `/dev/shm` sizing
**Avoids:** Pitfall 4 (Playwright flakiness — explicit `/dev/shm`, `--init`, pinned versions), Pitfall 5 (trigger race — single shared scheduler)

### Phase Ordering Rationale

- **Sandbox before generation:** Pitfall 1 is categorized as a "never acceptable" shortcut even in MVP (PITFALLS.md Technical Debt table). Building the sandbox first makes the correct execution boundary a structural constraint, not an afterthought applied retroactively.
- **Generation before auto-fix:** The auto-fix loop requires real test output as input; a standalone test generation + execution pass is the simplest testable slice and proves the end-to-end LLM→freellmapi→files→executor→comment flow before adding retry complexity.
- **Auto-fix before trigger wiring:** The trigger wiring (Phase 26) is the externally-visible interface. Having the full pipeline logic working in isolation before wiring up both triggers means integration testing can focus on the idempotency and race conditions specific to dual-trigger orchestration.
- **This order matches the ARCHITECTURE.md recommended build order (Phases 23→26)** with no changes — the pitfall analysis independently confirms the same sequence.

### Research Flags

Phases needing deeper research during planning:

- **Phase 23 (QA Foundation):** Toolchain auto-detection is flagged as the highest-complexity new component in this milestone (FEATURES.md). The marker-file detection approach is directionally correct but monorepo / mixed-stack edge cases are known unknowns. Recommend a focused spike on detection robustness before designing the detection module. Also verify Docker Engine API version compatibility between Python SDK `7.1.x` and the host's Docker Engine before committing to the sibling-container approach.
- **Phase 25 (Auto-Fix Loop):** Non-progress detection heuristic ("same error after a fix attempt") needs a concrete implementation design — hash/diff approach (stderr hash, assertion text similarity, diffing fix diffs) should be scoped during planning, not left to implementation.
- **Phase 26 (E2E + Triggers):** Playwright E2E test generation quality for arbitrary repos is inherently uncertain until tested against real onboarded projects. Plan for a validation pass with at least one real project before treating Phase 26 complete.

Phases with standard patterns (skip research-phase):

- **Phase 24 (Test Generation):** The generation pattern (prompt construction → `route_request` → `### FILE:` parsing → write to workspace → execute → post comment) is a direct extension of `code_generator.py`'s proven pattern with narrower context. No new research needed; implementation follows existing code as a template.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | MEDIUM-HIGH | Core library choices verified against existing codebase; exact patch versions for ruff/bandit/mypy/semgrep/docker SDK should be verified at implementation time, not copied verbatim from research |
| Features | HIGH | Feature scope derived directly from codebase inspection + PROJECT.md authoritative milestone scope; all P1 features trace to concrete existing code hooks or patterns |
| Architecture | HIGH | All integration points verified against live source files; four-phase build order confirmed independently by both architecture and pitfalls research |
| Pitfalls | HIGH (codebase-grounded) / MEDIUM (general patterns) | Six pitfalls all trace to specific existing code patterns or absence of patterns in the codebase; sandboxing/Playwright/auto-fix-loop patterns draw on 2024-2026 practitioner consensus |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Toolchain detection edge cases:** The marker-file detection approach is sound for pure Python and pure JS/TS repos. Monorepos (both in root), repos with custom test commands not following conventions, and repos with no detectable test framework need explicit handling. Flag for a spike before Phase 23 design is finalized.
- **Docker socket security model:** STACK.md identifies two options — mount `/var/run/docker.sock` into the `hermes` backend service (simpler, but grants container-escape risk to anything already running in `hermes` including LLM `Bash` tool calls), or a dedicated `qa-executor` sidecar service that owns the socket (more isolated). Make this decision explicitly during Phase 23 planning and document it in `PROJECT.md` as an accepted tradeoff.
- **Playwright version pinning logistics:** The `playwright` Python package minor version must match the `mcr.microsoft.com/playwright` Docker image tag. Re-verify against current Playwright releases at implementation time — `1.49.x` is the research-time recommendation but Playwright ships frequent minor releases.
- **freellmapi rate-limit behavior under sustained QA-loop load:** The cost model assumes freellmapi is "free" but not necessarily rate-limit-free under repeated codegen calls across multiple auto-fix iterations. Validate freellmapi container behavior under a 3-attempt × max_turns=30 scenario before Phase 25 ships.

## Sources

### Primary (HIGH confidence)

- Direct codebase inspection: `backend/services/dev_pipeline.py`, `backend/services/merge_pipeline.py`, `backend/services/agentic_coder.py`, `backend/services/repo_clone.py`, `backend/services/code_generator.py`, `backend/services/pr_creator.py`, `backend/routers/webhook.py`, `backend/models/pipeline_state.py`, `docker-compose.yml`, `backend/Dockerfile`, `backend/requirements.txt` — ground truth for all integration points and existing patterns
- `.planning/PROJECT.md` — authoritative milestone scope, constraints, and autonomy boundaries

### Secondary (MEDIUM confidence)

- Playwright Docker operational patterns — image/package version pairing requirement; `/dev/shm` sizing guidance; `--init` zombie-process reaping; headless Chromium container requirements
- Docker SDK for Python resource-limiting API (`mem_limit`, `nano_cpus`, `pids_limit`) — stable Docker Engine API surface
- Agentic coding tool QA/auto-fix patterns (Devin-style iterative loops, Cursor/Copilot Workspace background-agent test generation, CI auto-fix bot retry conventions) — 2024-2026 practitioner consensus on bounded-retry auto-fix loops and tool-grounded test generation

### Tertiary (LOW confidence)

- Exact patch versions for `ruff`/`bandit`/`mypy`/`semgrep`/`tenacity`/`docker` Python SDK — verify against PyPI at implementation time; stated versions are directionally correct but not guaranteed to be current at implementation date

---
*Research completed: 2026-06-23*
*Ready for roadmap: yes*
