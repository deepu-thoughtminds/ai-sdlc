# Pitfalls Research

**Domain:** Adding autonomous QA stage (test generation + sandboxed execution + bounded auto-fix loop) to existing Jira-comment-driven AI SDLC pipeline (FastAPI + Docker Compose + freellmapi/LiteLLM + Claude Agent SDK + GitHub dev/merge pipeline)
**Researched:** 2026-06-23
**Confidence:** HIGH (codebase-grounded findings on integration points and existing execution model), MEDIUM (general sandboxing/Playwright/auto-fix-loop industry patterns, since this exact feature is pre-implementation)

## Critical Pitfalls

### Pitfall 1: Test execution reuses the dev pipeline's unsandboxed code-execution model — QA stage inherits arbitrary code execution with no isolation

**What goes wrong:**
`agentic_coder.py` already runs the Claude Agent SDK with `allowed_tools=["Read", "Write", "Bash", "Glob", "Grep"]` directly against `cloned.workspace_path` — a temp directory on the **backend container's own filesystem**, not a separate sandbox container. `docker-compose.yml` confirms there is no Docker-socket-mounted "sandbox runner" service today; `dev_pipeline.py` clones, codegens, and PR-creates entirely inside the `hermes`/backend process. If the QA stage is built by simply reusing this same pattern — giving the LLM `Bash` access to `npm test`, `pytest`, or `npx playwright test` in the same workspace — every test run is **arbitrary code execution inside the application's own container**, with the same network access, same filesystem visibility, and same blast radius as the dev pipeline itself. Test generation doubles this risk: the LLM-generated test *code* now also executes with Bash-tool privileges, so a malicious or buggy generated test (e.g. one that does `rm -rf` relative to a wrong cwd, or curls internal service URLs like `litellm:4000` / `mcp-atlassian:9000`) has no isolation boundary stopping it from reaching sibling containers via `ai-sdlc-net`.

**Why it happens:**
- The dev/merge pipelines were built without sandbox isolation because codegen alone (Read/Write/Bash on a temp dir) felt "safe enough" for a single trusted developer's workspace — but *executing untrusted, LLM-generated test code* is a materially different risk than *writing* code that a human will review before merge.
- Reusing `agentic_coder.py`'s `ClaudeAgentOptions` pattern (same `allowed_tools`, same `cwd=workspace_path`) is the path of least resistance for an engineer extending the existing pipeline, but it silently inherits "no isolation" along with it.
- No Docker-in-Docker, gVisor, or microVM sandboxing exists anywhere in this stack today — Docker Compose services are all long-running, not ephemeral per-task sandboxes.

**How to avoid:**
- Introduce a dedicated, ephemeral sandbox execution path for the QA stage distinct from `agentic_coder.py`'s codegen pattern: a short-lived container (`docker run` per QA run, or a pre-built "qa-runner" image) with `--network=none` or an isolated network that cannot reach `ai-sdlc-net` service hostnames (`litellm`, `mcp-atlassian`, `freellmapi`), read-only mounts where possible, and explicit CPU/memory/pids limits (`--memory`, `--cpus`, `--pids-limit`).
- Never let the LLM's `Bash` tool calls run test commands directly inside the backend's own container process — the test *runner invocation* (`pytest`, `npm test`, `npx playwright test`) should be a single controlled subprocess call from QA pipeline code, not an LLM-issued shell command with open-ended privileges.
- If the backend needs `docker run` access to spin up sandbox containers, mount the Docker socket deliberately and narrowly (or use a sibling "qa-executor" service with its own Dockerfile) — do not casually add `/var/run/docker.sock` to the existing `hermes` service, since that grants host-level container escape to anything running inside it.

**Warning signs:**
- QA stage code passes `cwd=workspace_path` into the same `ClaudeAgentOptions`/`allowed_tools` pattern as `agentic_coder.py` with no new container boundary.
- Test execution subprocess calls have access to `ai-sdlc-net` (can resolve `litellm`, `freellmapi`, `mcp-atlassian` hostnames) during a test run.
- No resource limits (`ulimit`, `--memory`, timeout wrapper) on the process that invokes the test runner.

**Phase to address:**
QA sandbox execution phase — must be designed and built *before* test generation or auto-fix logic, since those features compound the blast radius of an unsandboxed executor.

---

### Pitfall 2: Auto-fix retry loop has no hard ceiling distinct from the LLM's own `max_turns`, risking runaway LLM cost and stuck pipeline state

**What goes wrong:**
`agentic_coder.py` bounds a single codegen call with `max_turns=30` (an SDK-internal turn limit for one invocation). The QA stage introduces a *second*, outer loop: generate tests → run tests → on failure, ask the agent to fix → re-run tests → repeat "up to a bounded retry limit" per the milestone goal. If that outer retry count is implemented loosely (e.g. a `while True` with a `break` condition that's easy to miscount, or a counter that resets on partial success), each retry iteration itself invokes `run_agentic_codegen`-style calls with their own `max_turns=30` — so a bug in the outer bound multiplies cost by 30x per missed-iteration, against freellmapi (intended to be cost-free, but not necessarily rate-limit-free) and against wall-clock time the Jira ticket is left in a "running" `PipelineState`. Worse, if the loop's exit condition only checks "tests pass" and never checks "did the auto-fix actually change anything," an LLM that produces a no-op or identical fix attempt every time will spin for the full retry budget without making progress, burning the entire allowance on a deterministically unfixable failure (e.g., a missing system dependency the LLM cannot install).

**Why it happens:**
- The milestone description says "bounded retry limit" but doesn't specify whether the bound is a turn count, wall-clock timeout, or a smarter convergence check (e.g., stop early if the same test still fails with the same error after a fix attempt) — without a concrete design here, the natural implementation is a simple counter that under-protects against pathological cases (looping fix attempts that don't change behavior).
- `dev_pipeline.py`/`merge_pipeline.py`'s existing pattern is "one LLM call, one outcome, post to Jira" — there is no precedent in this codebase yet for a multi-iteration LLM loop with intermediate state, so there's no existing convention to copy defensively.
- Background tasks here run via `asyncio.create_task` fire-and-forget from webhook handlers (per existing `architecture_pipeline`/`merge_pipeline` pattern) — there's no overall pipeline-level timeout wrapper today, so an auto-fix loop that doesn't terminate cleanly can run far longer than a human would tolerate before anyone notices, since nothing is watching wall-clock duration except the iteration counter itself.

**How to avoid:**
- Implement the retry bound as **both** a hard iteration count (e.g. 3 attempts) **and** a wall-clock timeout for the whole QA run, independent of how many LLM turns each attempt uses internally.
- Detect non-progress explicitly: hash or diff the failing test output between attempts; if the same test fails with materially the same error/stack trace after a fix attempt, stop early rather than spending the full retry budget (this also produces a more honest "this needs human help" signal for the Jira comment).
- Track retry count in `PipelineState` (a new column, mirroring how `complexity`/`complexity_rationale` were added in Phase 10) so a stuck or runaway loop is visible/queryable in the DB, not just inferred from logs — and so a crash mid-loop doesn't silently resume from iteration 0 on retry.
- Treat the auto-fix loop count as a *budget*, not a goal: each attempt should consume from the same shared budget that also accounts for total wall-clock time, so a slow sandbox (e.g. Playwright cold starts) can't be combined with the max iteration count to produce an unbounded total duration.

**Warning signs:**
- `PipelineState` rows for `stage="qa"` stuck in `status="running"` far longer than the dev/merge pipeline stages typically take.
- freellmapi/LiteLLM request logs show repeated near-identical codegen prompts for the same ticket in a short window.
- Auto-fix attempts produce diffs that are empty, revert-and-reapply the same change, or only touch comments/formatting — a sign the LLM is "fixing" without addressing the actual failure.

**Phase to address:**
Auto-fix loop phase — design the budget/convergence-detection logic explicitly as its own unit before wiring it to the sandbox executor, so the bound is enforced at the orchestration layer and not left to "the LLM will know when to stop."

---

### Pitfall 3: Auto-fix commits create stale codebase context mid-loop — the `.hermes/codebase.md` snapshot and `directory_tree` the agent reasons against goes out of date with every fix attempt

**What goes wrong:**
`merge_pipeline.py` already shows the established pattern: after a merge, `codebase_scan_service.run(...)` is triggered as a **post-merge** hook to refresh `.hermes/codebase.md` so future dev-pipeline runs see up-to-date codebase context (`SNAPSHOT-01`). The QA stage's auto-fix loop, however, operates *between* merges — each fix attempt modifies files in the cloned workspace, but nothing refreshes `directory_tree`/codebase summary context mid-loop, because that refresh mechanism today is explicitly tied to "PR merged to main," not "files changed in a working tree." If the auto-fix agent is given the same stale `directory_tree`/`architecture_content` snapshot for every retry attempt (captured once at QA-run start, per `dev_pipeline.py`'s existing pattern of computing `directory_tree` once before codegen), then after fix attempt #1 changes file structure (e.g., adds a new test helper file, renames a module to satisfy a lint rule), fix attempt #2's prompt still describes the *original* pre-fix codebase — the agent may re-create files that already exist, contradict its own prior edit, or "fix" code that fix attempt #1 already addressed differently, because its mental model of the repo is one iteration behind reality.

**Why it happens:**
- The existing codebase-context mechanism (`get_codebase_summary`, `.hermes/codebase.md`) was built around a single-shot dev pipeline (one codegen pass per ticket) and a clear "refresh on merge" trigger — it has no notion of intra-run incremental refresh, because no existing pipeline stage needed one.
- It's natural (and matches existing `dev_pipeline.py` Step 5 structure) to compute `directory_tree`/`codebase_context` once at the top of the QA run and pass the same value into every retry iteration's prompt, since that's exactly the shape of the existing one-shot dev pipeline call.
- Git state in the workspace *does* change between fix attempts (the working tree is mutated in place), but nothing re-reads `git ls-files`/directory structure or re-summarizes it before constructing the next fix prompt unless explicitly coded to do so.

**How to avoid:**
- Re-derive the lightweight, cheap parts of context (at minimum: `git status`/`git diff --stat` since the QA run started, and a fresh `directory_tree` via the same walk `dev_pipeline.read_relevant_files`/`graphify_service` already does) before constructing each auto-fix retry's prompt — this doesn't need the full expensive `.hermes/codebase.md` regeneration, just a cheap local re-scan of the workspace already on disk.
- Explicitly pass the previous attempt's diff/changes into the next fix prompt ("here is what was already changed in attempt N; do not revert or duplicate this work") rather than re-deriving everything from a static pre-loop snapshot — this is cheap and directly prevents contradicting prior fixes.
- Do not trigger a full `codebase_scan_service.run()`-style remote GitHub re-scan per retry attempt — that hook is designed for post-merge (expensive, GitHub API-backed) refresh, not a tight in-loop iteration; reserve the heavy refresh for after the QA stage's eventual fix is itself merged/pushed.

**Warning signs:**
- Auto-fix attempt N+1 re-introduces a file or pattern that attempt N already removed or renamed.
- Generated fix diffs include changes unrelated to the actual failing test, suggesting the agent is "rediscovering" structure it should already know from the immediately prior attempt.
- Final QA report shows the same file modified by multiple fix attempts in contradictory ways (e.g., import added then removed then re-added).

**Phase to address:**
Auto-fix loop phase — context-passing between iterations should be designed alongside the retry bound (Pitfall 2), since both concern what state flows from one iteration to the next.

---

### Pitfall 4: Flaky/non-deterministic test failures (especially Playwright E2E) get treated identically to genuine code defects, triggering wasted or harmful auto-fix attempts

**What goes wrong:**
Playwright E2E tests are well known to be flaky specifically when run inside containers — shared-memory crashes, timing assumptions that hold on a dev machine but break under container CPU/memory limits, font-rendering differences, and zombie browser processes are all documented container-specific failure modes (not generic test flakiness). If the QA stage's auto-fix loop treats *any* failing test as "the code is broken, ask the LLM to fix it," a transient Playwright crash (e.g., browser OOM from too little `/dev/shm`, or a `waitForSelector` race under container CPU throttling) will be handed to the auto-fix agent as if it were a real bug. The agent — having no way to distinguish "flaky infra failure" from "real defect" — will then "fix" working code in response to a non-reproducible failure, potentially introducing an actual regression to address a problem that didn't exist, and burning a retry-loop iteration (Pitfall 2's budget) on noise.

**Why it happens:**
- Flakiness from container resource constraints (insufficient `--shm-size`, too many parallel workers per CPU, x86 emulation on ARM hosts) is an infrastructure problem that looks identical to a test failure from the test runner's exit code alone — there's no signal distinguishing "assertion failed because the code is wrong" from "browser crashed because of insufficient shared memory" unless the QA pipeline specifically inspects stderr/exit codes for crash signatures.
- The dev/merge pipelines today have no precedent for "is this failure real or transient" classification — every existing failure path (`dev_pipeline`, `merge_pipeline`) treats any exception as `status="failed"` and reports it, with no retry-without-fix step.
- Docker Compose services in this project are long-running app containers sized for light request/response workloads; nobody has yet sized a container specifically for headless Chromium's memory/shm requirements (commonly cited guidance: 1-2GB `/dev/shm`, more under parallel load), so the QA sandbox container is likely to be under-provisioned by default if copied from the existing service resource profile.

**How to avoid:**
- Before invoking the auto-fix agent, retry the *exact same* failing test once or twice in isolation (no code changes) inside the sandbox; if it passes on retry, classify it as flaky and report it as such in the Jira comment rather than feeding it to the fix loop — this single check eliminates the majority of wasted fix attempts.
- Explicitly size the Playwright sandbox container with adequate `--shm-size` (start at 1GB, consider 2GB+ under parallel test execution) and pass `--init` to reap zombie browser processes; do not inherit the default shm size of other lightweight services in `docker-compose.yml`.
- Keep Playwright runs headless in the sandbox (never headed) and pin the Playwright npm package version to match the browser binaries baked into whatever base image is used — version drift between library and browser binary is a common silent failure source distinct from real flakiness.
- Surface flaky-vs-real distinction in the final Jira comment so a human reviewing exhausted-retry QA results can tell "this genuinely failed after N fix attempts" apart from "this is intermittently flaky infra, consider re-running."

**Warning signs:**
- The same test fails and passes across consecutive QA runs on identical code (no commits in between).
- Auto-fix loop "fixes" a test by modifying application code in ways unrelated to the assertion that failed.
- QA sandbox container logs show browser crash signatures (`Target closed`, `Protocol error`, OOM kills) rather than clean assertion failures.

**Phase to address:**
Test execution/sandbox phase — flaky-detection (retry-without-fix) must exist before the auto-fix loop is wired up, otherwise the auto-fix phase has no way to gate against feeding it noise.

---

### Pitfall 5: QA stage's two trigger paths (auto-chain post-merge, and on-demand `@jarvis run qa`) race or duplicate against the same idempotency machinery the merge pipeline already depends on

**What goes wrong:**
The milestone explicitly wants QA to "auto-chain dev pipeline's PR merge completes" **and** be re-triggerable via `@jarvis run qa` comment. `merge_pipeline.py` already runs a post-merge hook (`codebase_scan_service.run(...)`) inside its own try/except, isolated from the merge's own `state_row.status`/commit. If the QA auto-chain is implemented as "after merge_pipeline finishes, immediately schedule QA," and a user *also* posts `@jarvis run qa` manually (e.g., because they don't trust the auto-chain fired, or want to re-run after seeing the first QA result), the same idempotency pattern used for `architecture`/`merge_pr` stages (`webhook.py` checking for an existing `PipelineState(stage=X, status="running")` row before scheduling) must be replicated correctly for the new `qa` stage — and the auto-chain path is a *second* code path that schedules the same background task outside the webhook handler's existing dedupe check. If the auto-chain trigger doesn't go through the same idempotency guard as the comment-triggered path (because it's invoked directly from `merge_pipeline.run()` rather than re-entering `webhook.py`'s mention-routing logic), a manual `@jarvis run qa` posted shortly after a merge can race the auto-chained run, producing two concurrent `PipelineState(stage="qa", status="running")` rows that both clone the repo, both run tests, and potentially both attempt auto-fix commits/pushes to the same branch simultaneously.

**Why it happens:**
- The existing idempotency guard pattern lives in `webhook.py`'s mention-dispatch logic (checking `PipelineState.status.in_(["running"])` before creating a new row), which is naturally bypassed if the auto-chain is wired as a direct function call from inside `merge_pipeline.run()` rather than as a synthetic event re-entering the same webhook dispatch path.
- Auto-chaining "feels like" just calling the next function in sequence (similar to how `codebase_scan_service.run()` is called inline after a merge), but unlike that fire-and-forget snapshot refresh, the QA stage produces its own `PipelineState` row, posts its own Jira comment, and can push commits — it has all the same race-condition surface as a comment-triggered stage and needs the same guard.
- Two trigger paths for one stage is new in this codebase — every existing stage (`describe`, `architecture`, `dev_pipeline`/`start coding`, `merge_pr`) has exactly one trigger phrase, so there's no existing precedent here to copy defensively.

**How to avoid:**
- Route the auto-chain trigger through the *same* idempotency-checked scheduling path the comment trigger uses (e.g., have `merge_pipeline.run()` call the same internal "schedule QA stage" helper that `webhook.py`'s `@jarvis run qa` handler calls, rather than duplicating the background-task creation logic) so there is exactly one code path that creates `PipelineState(stage="qa", status="running")` rows, and exactly one dedupe check guarding it.
- Apply the existing `status.in_(["running"])` pre-check pattern (used for `architecture`/`merge_pr`) to the `qa` stage before either trigger path schedules a new background task — auto-chain should silently no-op (or post "QA already running") if a run is already active, exactly like a duplicate webhook redelivery would.
- Decide explicitly whether a manual `@jarvis run qa` posted while an auto-chained run is in progress should queue, replace (supersede), or be rejected with an informative comment — and make that decision visible in the Jira comment so users aren't confused by silence.

**Warning signs:**
- Two `PipelineState(stage="qa")` rows with overlapping `created_at`/`status="running"` timestamps for the same `ticket_key`.
- Duplicate or conflicting QA result comments posted to the same Jira ticket close together in time.
- Two auto-fix loops pushing commits to the same branch concurrently, producing merge conflicts or force-push races in the sandboxed clone-and-push step.

**Phase to address:**
QA trigger/orchestration phase — should be scoped explicitly to define the single scheduling path before either trigger (auto-chain or comment) is wired up, mirroring the idempotency convention already established for `architecture` and `merge_pr`.

---

### Pitfall 6: Auto-fix commits pushed without going through the existing PR-creation/review contract bypass the human-review safety net the dev pipeline relies on

**What goes wrong:**
`dev_pipeline.py`'s entire autonomy model rests on: agent writes code → `apply_commit_push_and_open_pr` opens a **PR** → a human reviews and the `merge_pr` trigger is a separate, explicit, human-initiated step. The QA stage's auto-fix loop, if implemented to push fix commits directly to the already-merged `main` branch (since QA runs *after* merge, per the milestone's "auto-chains dev pipeline's PR merge completes"), bypasses this review gate entirely — autonomous code changes would land on `main` with no PR, no diff for a human to see before it's live, and no `merge_pr`-style explicit approval step. This inverts the project's stated autonomy boundary (`PROJECT.md`: "Dev stage is fully autonomous code changes — requires robust codebase reading and PR creation" — autonomy is explicitly scoped to *PR creation*, not direct-to-main commits) and means a bad auto-fix (e.g., one that "fixes" a failing test by weakening the assertion, or by deleting the test) ships straight to production code with zero human checkpoint.

**Why it happens:**
- The milestone framing ("auto-chains dev pipeline's PR merge completes... attempting bounded auto-fix loop on failures") is ambiguous about *where* the auto-fix commits land — it's tempting to implement "fix and push" as directly committing to the branch that was just merged, since that's the simplest mechanical path and the code is already on `main`.
- There's schedule pressure to make the auto-fix loop feel "fully autonomous" end-to-end, and inserting a second PR-and-approval cycle for QA fixes feels like it undermines that goal — but the existing dev pipeline's autonomy already stops at PR creation, not merge, for exactly this reason.
- No existing pipeline stage in this codebase pushes commits to `main` directly; `pr_creator.py`'s `apply_commit_push_and_open_pr` is the only commit-pushing code path today, and it always produces a PR, never a direct push.

**How to avoid:**
- Auto-fix commits should open a **new PR** (or push to a dedicated `jarvis/qa-fix-{issue_key}` branch and open a PR against `main`, mirroring the existing `jarvis/issue-{key}` branch convention `pr_creator.py`/`merge_pipeline.py` already use), never push directly to `main` — this preserves the existing human-review checkpoint and reuses `apply_commit_push_and_open_pr` rather than inventing a new unreviewed commit path.
- If the goal is genuinely full autonomy through merge, that should be an explicit, separately-flagged decision (e.g., requiring an additional `@jarvis approve qa-fix` comment trigger, mirroring the `approval_detector.py` pattern already used for architecture approval) rather than an implicit side effect of how the auto-fix loop happens to be wired.
- Final QA Jira comment should clearly state whether fixes were auto-merged or are awaiting review in a new PR, so there's no ambiguity about what state the codebase is actually in.

**Warning signs:**
- Auto-fix loop code calls `git push origin main` (or pushes to whatever branch is checked out) rather than creating a new branch + PR.
- No new PR appears in GitHub for tickets where the auto-fix loop ran and "succeeded."
- `main` branch history shows commits authored by the agent with no corresponding PR/review trail, breaking the audit trail the rest of the pipeline maintains (every other autonomous code change traces back to a PR).

**Phase to address:**
Auto-fix loop phase — the commit/push strategy must be decided explicitly as part of this phase's design, not left as an implementation detail, since it determines whether the milestone preserves or breaks the project's existing human-review autonomy boundary.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|------------------|
| Reuse `agentic_coder.py`'s `ClaudeAgentOptions`/`Bash`-tool pattern directly for test execution instead of building a dedicated sandbox | Fast to ship — no new container/orchestration code | Unsandboxed test execution inside the app's own container (Pitfall 1); compounds with auto-fix to execute LLM-generated code with no isolation | Never — even an MVP QA stage needs *some* process-level isolation (subprocess timeout + resource limits at minimum) before "autonomous" execution of generated tests |
| Auto-fix loop bound expressed only as a simple iteration counter, no convergence/non-progress detection | Simpler to implement and reason about | Wastes the entire retry budget on deterministically unfixable failures (Pitfall 2); can't distinguish "making progress slowly" from "stuck" | Acceptable for a first internal-only milestone if the iteration count is small (e.g. 2) and wall-clock-bounded, but should be revisited before wider rollout |
| Compute `directory_tree`/codebase context once at QA-run start and reuse for every retry attempt | Matches existing one-shot `dev_pipeline.py` pattern, less new code | Stale context across fix iterations (Pitfall 3) — agent contradicts or duplicates its own prior fixes | Only acceptable if each retry prompt also includes the literal diff of all prior fix attempts so the agent has *some* up-to-date signal even without a full re-scan |
| Auto-fix commits pushed directly to `main` (or the already-merged branch) instead of opening a new PR | Feels "more autonomous," fewer moving parts | Breaks the project's existing PR-review checkpoint (Pitfall 6); no audit trail for autonomous fix commits | Never — this contradicts the project's documented autonomy boundary ("requires... PR creation") and should not ship even in MVP |
| Treat every test failure as a real defect with no flaky-retry check before invoking auto-fix | Simpler control flow | Wastes retry budget and risks "fixing" working code in response to container-induced Playwright flakiness (Pitfall 4) | Acceptable only for unit tests/static analysis (genuinely deterministic); never acceptable once Playwright E2E tests are in scope |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|-------------------|
| Claude Agent SDK / `agentic_coder.py` pattern reused for QA | Passing the same `allowed_tools=["Bash", ...]` config into a test-execution context, letting the LLM directly invoke test runner commands with full shell access | Keep LLM tool access for *generating* test files; invoke the actual test runner via a controlled, sandboxed subprocess call from QA pipeline code, not an LLM-issued `Bash` tool call |
| Docker Compose / sandbox container provisioning | Sizing the QA/Playwright sandbox container with the same defaults as existing lightweight services (`hermes`, `litellm`), under-provisioning `/dev/shm` and CPU/memory for headless Chromium | Explicitly set `--shm-size` (1GB+, more under parallel load), CPU/memory limits, and `--init` for zombie-process reaping on the QA sandbox container; do not copy resource settings from unrelated services |
| `PipelineState` idempotency guard (existing pattern for `architecture`/`merge_pr`) | Wiring the post-merge auto-chain trigger as a direct function call from `merge_pipeline.run()` that bypasses the webhook-level dedupe check used by the comment-triggered path | Route both QA trigger paths (auto-chain and `@jarvis run qa`) through one shared scheduling helper with the same `status.in_(["running"])` pre-check used for other stages |
| `pr_creator.py` / branch-and-PR convention (`jarvis/issue-{key}`) | Auto-fix loop pushing fixes directly to `main` instead of a new branch+PR | Reuse `apply_commit_push_and_open_pr` with a distinct branch name (e.g. `jarvis/qa-fix-{issue_key}`) for auto-fix commits, preserving the existing review checkpoint |
| `codebase_scan_service` post-merge refresh hook | Assuming this hook also covers intra-QA-loop context freshness, or triggering a full remote re-scan on every auto-fix iteration | Use cheap local re-scans (`git diff --stat`, local directory walk) between auto-fix iterations; reserve the expensive GitHub-API-backed `codebase_scan_service.run()` for genuine post-merge events only |
| freellmapi/LiteLLM proxy under retry-loop load | Assuming freellmapi has unlimited free capacity for repeated codegen calls across every auto-fix iteration with no backoff | Add iteration-aware rate limiting/backoff in the auto-fix loop so a stuck loop doesn't hammer freellmapi/LiteLLM with rapid repeated requests; monitor freellmapi container health under sustained QA-loop load |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|------------------|
| Playwright E2E tests run with default/no resource limits inside a generic container | Intermittent browser crashes, `Target closed`/`Protocol error` failures, OOM kills only under CI/sandboxed conditions, not on a dev machine | Size `/dev/shm` (1GB+), cap parallel workers relative to container CPU allocation, use `--init` for process reaping | Becomes visible as soon as more than 1-2 E2E tests run in parallel, or whenever the sandbox container shares host resources with other services under load |
| Auto-fix loop's per-iteration LLM call (with its own internal `max_turns`) multiplied by outer retry count with no combined wall-clock cap | A single QA run for one ticket can silently run for many multiples of a normal dev-pipeline run's duration, holding `PipelineState` at `status="running"` far longer than expected | Enforce a combined wall-clock timeout across the entire QA run (sandbox boot + test execution + all fix attempts), independent of per-attempt turn limits | Becomes a real production issue once QA auto-chains after every merge — a single slow/stuck ticket can occupy sandbox resources while subsequent merges queue behind it if sandbox capacity is shared/serialized |
| Full repo re-clone + fresh sandbox container boot for every auto-fix retry iteration | QA stage latency dominated by repeated clone/container-startup overhead rather than actual test execution time | Reuse the same cloned workspace and sandbox container across retry iterations within one QA run (only re-clone/reboot for a genuinely new QA trigger), applying only the incremental fix diff between iterations | Becomes noticeable once retry count is more than 1-2 and clone/boot time is a meaningful fraction of total test execution time (likely for Playwright-heavy suites) |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Granting the QA sandbox container network access to `ai-sdlc-net` (so it can resolve `litellm`, `mcp-atlassian`, `freellmapi` hostnames) | LLM-generated test code or a compromised/buggy auto-fix attempt can reach internal services directly, potentially exfiltrating the LiteLLM master key, hitting internal APIs with unintended requests, or pivoting to other containers | Run the QA sandbox on an isolated network (or `--network=none` for unit/static-analysis steps; a narrowly-scoped network only if outbound internet access is genuinely required for E2E tests), never the same Compose network as the credential-handling backend services |
| Mounting the Docker socket into the `hermes`/backend service to let it spin up sandbox containers | Full host-level container escape — anything that can execute arbitrary Bash inside `hermes` (which `agentic_coder.py` already grants the LLM) gains effective root on the host via Docker socket access | If sandbox containers must be spawned dynamically, use a separate, minimally-privileged "qa-executor" sidecar service with the socket access isolated there, not on the same service that already runs untrusted LLM-driven Bash commands |
| Passing `github_token`/`jira_token` into the QA sandbox environment so the auto-fix loop can push commits from inside the sandbox | Credentials present inside a less-trusted, test-code-executing environment increases exposure surface compared to the existing pattern (`T-16-05`/`T-17-05`) of only passing tokens to dedicated, audited functions like `apply_commit_push_and_open_pr` | Keep credential decryption and git push/PR-creation logic outside the sandbox, in the existing trusted pipeline-orchestration code — the sandbox should only receive the workspace files and produce a diff/patch, with push happening from the orchestrator using the existing `pr_creator.py` path |
| LLM-generated test assertions or fixtures that embed ticket description content verbatim into test files without sanitization | If a malicious/crafted Jira ticket description contains shell metacharacters or code-injection payloads, and that text flows into generated test file content executed by the test runner, it could result in unintended code execution beyond the test's intended scope | Treat ticket description/summary text as untrusted input throughout — the existing `dev_pipeline.py` already keeps tokens out of prompts (T-16-05/06); extend the same discipline to ensure generated test content is reviewed/diffed before execution, and avoid constructing shell commands by string-interpolating ticket text |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-------------------|
| Final Jira comment reports only pass/fail with no indication of how many auto-fix attempts were made or what changed | Reviewer can't tell whether a "passing" result represents original code or several rounds of autonomous modification, undermining trust in the result | Always state attempt count and link/summarize what each fix attempt changed, even on eventual success, mirroring the architecture stage's "rationale" transparency pattern already recommended for that feature |
| QA results reported only after all retries exhaust, with no intermediate visibility for a long-running loop | User has no signal whether QA is progressing or stuck, especially if the combined run takes much longer than the familiar dev/merge pipeline stages | Consider an intermediate "QA in progress, attempt N of M" comment update (or at minimum, ensure `PipelineState.status="running"` is queryable) so a stuck loop is distinguishable from a slow-but-progressing one |
| Auto-chained QA runs silently after merge with no clear signal distinguishing it from a manually-triggered `@jarvis run qa` | Confusing when both triggers produce similarly-formatted comments — a user posting `@jarvis run qa` shortly after merge may not realize one already ran/is running | Label QA result comments with their trigger source ("Auto-triggered after merge" vs. "Triggered by @jarvis run qa") so users understand why and when a given QA run happened |

## "Looks Done But Isn't" Checklist

- [ ] **Sandboxed test execution:** Often "done" by reusing `agentic_coder.py`'s Bash-tool pattern with no real container/process isolation — verify test runner invocation happens in a genuinely isolated process/container with resource limits and no access to `ai-sdlc-net` service hostnames, not just "runs inside the cloned workspace."
- [ ] **Bounded auto-fix loop:** Often "done" with just an iteration counter — verify there's also a wall-clock timeout, a non-progress/convergence check (same failure recurring after a fix attempt), and the retry count is persisted in `PipelineState` so a crash mid-loop doesn't silently restart from zero.
- [ ] **Auto-fix commit strategy:** Often "done" by pushing directly to the merged branch — verify auto-fix commits go through a new branch + PR via the existing `pr_creator.py` path, preserving the human-review checkpoint the rest of the pipeline relies on.
- [ ] **Playwright E2E execution:** Often "done" with default container settings — verify `/dev/shm` sizing, `--init` zombie-process reaping, headless-only execution, and pinned Playwright/browser binary versions are explicitly configured, not inherited from unrelated service defaults.
- [ ] **Flaky-test handling:** Often missing entirely — verify there's a retry-without-fix step that distinguishes transient/infra failures from genuine code defects before any failure is handed to the auto-fix agent.
- [ ] **QA trigger idempotency:** Often missing for the *auto-chain* path specifically (since the comment-triggered path may correctly copy the existing `architecture`/`merge_pr` guard, while the auto-chain bypasses it as a direct function call) — verify both trigger paths go through one shared, dedupe-checked scheduling function.
- [ ] **Credential handling in sandbox:** Often "done" by passing tokens into the sandbox for convenience — verify `github_token`/`jira_token` never enter the sandbox execution environment; they should only be used by the existing trusted orchestrator code (`pr_creator.py`, `hermes_client.py`) outside the sandbox boundary.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|------------------|
| Unsandboxed test execution already shipped and running in production | HIGH | Requires re-architecting the execution path into an isolated container/process before any further QA runs are trusted; audit logs for any signs of cross-container access or unexpected network calls during past QA runs |
| Auto-fix loop got stuck/runaway on a real ticket | LOW | Add wall-clock timeout + non-progress detection retroactively; manually mark the stuck `PipelineState` row as `failed` and post a corrective Jira comment; no automated fix possible for already-stuck runs beyond manual intervention |
| Auto-fix commits already pushed directly to `main` without PR review | MEDIUM | Audit `main` history for agent-authored commits with no corresponding PR; retroactively open review PRs for any unreviewed changes if still feasible, or treat them as already-shipped and add monitoring; fix the push path going forward immediately |
| Flaky Playwright failures already triggered several wasted/harmful auto-fix attempts on a ticket | LOW | Add the retry-without-fix flaky check going forward; for the affected ticket, manually review whether the "fix" commits introduced any unwanted changes and revert if so |
| Duplicate concurrent QA runs raced and produced conflicting commits/comments | MEDIUM | Add the shared idempotency guard immediately; manually reconcile any conflicting branches/PRs created by the race, and clean up duplicate `PipelineState` rows |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|---------------|
| Unsandboxed test execution (Pitfall 1) | Sandbox execution phase (build first, before test generation/auto-fix) | Test runner invocation happens in a container/process with no `ai-sdlc-net` access, explicit resource limits, and is invoked by orchestrator code rather than LLM-issued Bash calls |
| Unbounded/non-converging auto-fix loop (Pitfall 2) | Auto-fix loop phase | Iteration count + wall-clock timeout both enforced; non-progress detection causes early exit with a distinct "needs human help" Jira message; retry count persisted in `PipelineState` |
| Stale codebase context across fix iterations (Pitfall 3) | Auto-fix loop phase (alongside Pitfall 2's design) | Each retry prompt includes a fresh local re-scan or explicit prior-attempt diff; auto-fix attempt N+1 doesn't recreate/contradict attempt N's changes in test fixtures |
| Flaky test failures treated as real defects (Pitfall 4) | Test execution/sandbox phase | Retry-without-fix check exists and gates entry into the auto-fix loop; Jira comment distinguishes flaky from genuine failures; Playwright sandbox sized with adequate `/dev/shm` and `--init` |
| QA trigger race/duplication (Pitfall 5) | QA trigger/orchestration phase | Both auto-chain and `@jarvis run qa` paths route through one shared, dedupe-checked scheduler; concurrent-trigger test confirms only one active `PipelineState(stage="qa")` row at a time |
| Auto-fix bypasses PR review checkpoint (Pitfall 6) | Auto-fix loop phase | Auto-fix commits always land via a new branch + PR through `pr_creator.py`, never a direct push to `main`; Jira comment clearly states fix is awaiting review (or names the approval trigger if full autonomy is explicitly chosen) |

## Sources

- Direct codebase inspection: `backend/services/dev_pipeline.py`, `backend/services/merge_pipeline.py`, `backend/services/agentic_coder.py`, `backend/services/repo_clone.py`, `backend/models/pipeline_state.py`, `backend/routers/webhook.py`, `docker-compose.yml`, `litellm/config.yaml`, `.planning/PROJECT.md` — establishes the existing unsandboxed Bash-tool execution model, existing idempotency guard pattern, existing PR-only autonomy boundary, and existing post-merge codebase-refresh hook this milestone must integrate with.
- [Best Code Execution Sandboxes for AI Agents in 2026 — Modal Blog](https://modal.com/resources/best-code-execution-sandboxes-ai-agents)
- [What's the best code execution sandbox for AI agents in 2026? — Northflank](https://northflank.com/blog/best-code-execution-sandbox-for-ai-agents)
- [Sandboxed Environments for AI Coding: The Complete Guide — Bunnyshell](https://www.bunnyshell.com/guides/sandboxed-environments-ai-coding/)
- [Fault-Tolerant Sandboxing for AI Coding Agents: A Transactional Approach to Safe Autonomous Execution (arXiv)](https://arxiv.org/pdf/2512.12806)
- [Agentic CI Pipelines: Autonomous Code Review & Testing Tutorial — Nandann Creative Agency](https://www.nandann.com/blog/agentic-ci-pipelines-autonomous-code-review-testing)
- [Beyond Autocomplete: Best Agentic Coding Workflow in 2026 — Kilo](https://kilo.ai/articles/beyond-autocomplete)
- [Playwright Tests Fail in CI? Fix Common Pipeline Issues](https://software-testing-tutorials-automation.com/2026/05/playwright-tests-fail-in-ci-fix.html)
- [Playwright Docker: Stop Chasing Missing Browser Libraries in CI — Autonoma](https://getautonoma.com/blog/playwright-docker-guide)
- [Run integration-test with playwright inside a docker container, the pros and cons — Summerbud](https://www.summerbud.org/dev-notes/run-playwright-integration-test-in-docker-container)
- [Playwright in Docker: A Strategic Guide for 2026 — Bug0](https://bug0.com/knowledge-base/playwright-docker)

---
*Pitfalls research for: Autonomous QA stage (test generation + sandboxed execution + bounded auto-fix loop) added to AI-SDLC Jira's existing Jira-comment-driven SDLC pipeline*
*Researched: 2026-06-23*
