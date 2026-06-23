# Stack Research

**Domain:** Autonomous QA stage (test generation + sandboxed execution + bounded auto-fix loop) for an existing Python/FastAPI + Next.js + Docker Compose agentic SDLC platform — milestone v1.8
**Researched:** 2026-06-23
**Confidence:** MEDIUM-HIGH (core libraries verified against known-current major versions and existing repo conventions; sandboxing approach is an architectural recommendation grounded in the existing codebase, not a single verifiable "latest version" claim)

## Context Recap (what already exists — not re-researched)

- `backend/services/agentic_coder.py`: Claude Agent SDK (`claude-agent-sdk==0.2.107`) → `ClaudeAgentOptions(env={"ANTHROPIC_BASE_URL": "http://litellm:4000", ...})` → LiteLLM proxy → freellmapi. Runs `query()` with `allowed_tools=["Read","Write","Bash","Glob","Grep"]`, `permission_mode="acceptEdits"`, `max_turns=30`.
- `backend/services/repo_clone.py`: clones into `tempfile.mkdtemp()` on the **backend container's own filesystem** via `subprocess.run(["git", "clone", ...])` (list form, no `shell=True`). Caller (`dev_pipeline.py`) does `shutil.rmtree(...)` in a `finally` block.
- `backend/services/claude_code_executor.py` / `agentic_coder.py`: both run agentic tool loops with `Bash` enabled directly against that same temp workspace — i.e. **arbitrary commands from an LLM already execute inside the backend container today**, with no extra isolation. This is the existing risk posture the new QA stage inherits and must not make worse.
- `backend/Dockerfile`: `python:3.12-slim` + `git`, `nodejs`, `npm` installed; no Docker-in-Docker, no `docker` CLI, no Playwright browsers installed.
- `merge_pipeline.py` already has a clean "fire and forget, isolated try/except, never block main flow" pattern for post-merge hooks (`codebase_scan_service.run(...)`) — the QA auto-chain should follow this exact shape (wrap in try/except, never affect merge's own `state_row.status`/comment).
- `.hermes/codebase.md` (via `codebase_scan_service` / `codebase_snapshot_reader`) is the existing condensed codebase-context artifact already fed into prompts — QA test generation should reuse this same artifact rather than re-walking the repo.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `claude-agent-sdk` | `0.2.107` (already pinned — reuse, do not bump for this milestone) | Drive test-generation + auto-fix tool loops | Already the project's standard agentic-coding interface (used by `agentic_coder.py`); reuse the same LiteLLM-proxied pattern for QA so there is exactly one agentic-loop integration point in the codebase, not two parallel ones |
| Docker SDK for Python (`docker`) | `7.1.0` | Launch an ephemeral, resource-limited sibling container to run the cloned repo's test suite instead of executing it in-process in the backend container | The backend container currently has no isolation boundary for executing repo-supplied commands. QA introduces a NEW class of risk distinct from codegen: running the target repo's *own* `npm test` / `pytest` / lint / Playwright commands — fully arbitrary, dev-controlled strings from an onboarded repo. A short-lived container with CPU/memory/pid/network limits and a workspace-only bind mount is the minimum viable sandbox boundary, proportionate to this project's "trusted internal team, autonomous execution" threat model (see PROJECT.md Constraints) without adopting a heavier gVisor/Firecracker stack this team doesn't need |
| `playwright` (Python) | `1.49.x` | Generate + run E2E browser tests against the running app inside the sandbox | Matches Playwright's own Docker-first execution model (`mcr.microsoft.com/playwright/python` base images ship browsers preinstalled), avoiding repeated Chromium/Firefox downloads per QA run when the sandbox image is built once and reused across tickets |
| `mcr.microsoft.com/playwright:v1.49.0-noble` (pin to match the `playwright` package's exact minor) | pinned | Sandbox container base image for the QA runner | Browser binary version MUST match the `playwright` package's minor version exactly — mismatches are the single most common cause of "Playwright test passes locally, fails in sandbox" failures; pinning the image tag to the package version removes that failure class entirely |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `ruff` | `0.8.x` | Lint pass for Python target repos | Run when the cloned repo is detected as Python (presence of `requirements.txt`/`pyproject.toml`); fast enough to run unconditionally inside the bounded retry loop's time budget |
| `bandit` | `1.8.x` | Security static analysis for Python target repos | Run as a distinct "security scan" step, separate from lint — keeps the QA summary's failure categories (unit / lint / type / security / E2E) cleanly separated in the Jira comment, matching the milestone's explicit feature breakdown |
| `mypy` | `1.13.x` | Type-check pass for Python target repos | Only run if the target repo already has a `mypy.ini` / `[tool.mypy]` section or type hints present; skip silently otherwise rather than generating noisy false-failures on untyped repos |
| `eslint` (target repo's own config) | repo-detected, do not pin a Hermes-side version | Lint pass for JS/TS target repos | Always prefer the **target repo's own** lint config/deps — invoke via `npm run lint` if the script exists; the QA stage operates against arbitrary onboarded repos (which may include this very platform's own Next.js frontend), so it must not impose Hermes's own ESLint version on the target |
| `semgrep` | `1.9x.x` (CLI via `returntocorp/semgrep` image) | Security/SAST fallback for non-Python or polyglot repos | Single cross-language tool (JS/TS/Go/Java/etc.) avoids per-language scanner sprawl when the target repo isn't pure Python |
| `pytest` + `pytest-asyncio` | `8.3.x` / `0.24.x` (already pinned in `backend/requirements.txt` — reference only, target repo uses its own) | Unit test generation target framework when cloned repo is Python | Generate tests using the target repo's own existing test framework/conventions (detected from its `requirements.txt`/`pyproject.toml`), never a framework imposed by Hermes |
| `vitest` / `jest` (target repo's own) | repo-detected, do not pin | Unit test generation target framework when cloned repo is JS/TS | Detect from the target repo's `package.json` `devDependencies` + existing test script |
| Docker SDK resource-limit kwargs (`mem_limit`, `nano_cpus`, `pids_limit`, `network_mode`) | n/a — API surface of the `docker` package above | Bound the sandbox container's blast radius | `pids_limit` specifically guards against fork-bomb-style failures from a buggy generated test; default `network_mode="none"`, switching to a bridge network only when E2E tests must reach a locally-started instance of the app under test |
| `tenacity` | `9.0.x` | Implement the bounded auto-fix retry loop's attempt-counting/backoff | Idiomatic, testable "retry N times with a clear give-up condition" — cleaner than a hand-rolled `for attempt in range(N)` scattered through pipeline code, and gives structured per-attempt logging for free |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `docker compose` (existing) | Source of the QA sandbox runner | Backend launches an ephemeral sibling container per QA invocation via the Docker SDK (`docker run` equivalent) rather than standing up a persistent `qa-runner` Compose service — mirrors the existing `tempfile.mkdtemp()`-then-cleanup pattern already used for repo clones, and avoids a long-lived service accumulating stale state between tickets |
| Docker socket mount (`/var/run/docker.sock`) | Lets the `backend` container launch sibling sandbox containers | Real security tradeoff (socket access ≈ root on host). Document explicitly as an accepted risk consistent with PROJECT.md's existing "Dev stage is fully autonomous code changes" constraint, OR isolate the blast radius further by adding a small dedicated `qa-executor` sidecar service that owns the socket mount and is only reachable from `backend` over the internal `ai-sdlc-net` network — keeping socket access off the main FastAPI app entirely |

## Installation

```bash
# backend/requirements.txt additions
docker>=7.1.0,<8.0.0
tenacity>=9.0.0,<10.0.0
```

```yaml
# docker-compose.yml — backend service additions
services:
  backend:
    volumes:
      - ./backend:/app
      - app_data:/app/data
      - /var/run/docker.sock:/var/run/docker.sock   # required for sibling-container sandboxing
```

```dockerfile
# New: backend/qa-sandbox/Dockerfile (built once, reused per QA run)
FROM mcr.microsoft.com/playwright:v1.49.0-noble
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip nodejs npm git && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir ruff==0.8.* bandit==1.8.* mypy==1.13.* pytest==8.3.* pytest-asyncio==0.24.*
RUN npm install -g eslint semgrep
WORKDIR /workspace
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|--------------|-------------|--------------------------|
| Docker SDK + ephemeral sibling container per QA run | gVisor / Firecracker microVM sandbox | Only if the platform later onboards genuinely untrusted/public repos at scale; for an internal team's own onboarded projects, container resource limits are proportionate given the project's existing trusted-autonomy threat model |
| `docker` Python SDK calling `docker run` | Kubernetes Jobs | Only relevant if/when the platform migrates off Docker Compose to k8s — premature now given Constraints explicitly say Docker Compose |
| Single reusable `qa-sandbox` image with Playwright + ruff + bandit + mypy + eslint + semgrep preinstalled | Building a fresh image per QA run from the target repo's own Dockerfile | Use the target-repo-Dockerfile approach only when a project's test suite has unusual native dependencies the shared image can't satisfy — adds image-build latency to every QA run, so keep it project-opt-in, not default |
| `tenacity` for the auto-fix retry loop | Hand-rolled `for attempt in range(MAX_RETRIES)` | Fine if the team prefers zero new dependencies — `tenacity` mainly buys cleaner backoff/logging semantics, not new capability |
| Detect and reuse the target repo's own test runner/lint config | Impose one canonical toolchain (always pytest, always eslint) regardless of target repo | Never impose a canonical toolchain — onboarded repos are arbitrary client codebases; QA must adapt, mirroring how `dev_pipeline.py` already reads `directory_tree`/`codebase_context` before generating code |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|--------------|
| Running target-repo test/lint commands directly inside the `backend` FastAPI container (extending `claude_code_executor.py`'s pattern to QA execution) | The dev pipeline already accepts this risk for *agent-authored edits* with `Bash` tool access, but QA additionally executes the **target repo's own test/build scripts verbatim** (`npm test`, `npm run e2e`, arbitrary `package.json`/`Makefile` scripts) — far more likely to install global deps, hit unexpected network endpoints, or spawn runaway processes than a scoped agentic edit loop | Sibling sandbox container per QA run with resource + network limits (see Core Technologies) |
| `selenium` / `selenium-wire` for E2E generation | Slower, flakier, heavier setup (separate driver binaries per browser) than Playwright; no existing Selenium investment in this codebase to preserve | `playwright` (Python) |
| Unbounded `while True` auto-fix loop | Directly violates the milestone's explicit "bounded retry limit" requirement; risks runaway freellmapi/LLM cost on a stuck failure | Fixed `max_attempts` (e.g. 3) via `tenacity.stop_after_attempt()` or an explicit loop counter, with a clear "exhausted retries" terminal state surfaced in the final Jira comment |
| Reusing `claude_code_executor.py`'s raw `claude --dangerously-skip-permissions` CLI subprocess approach for the QA *test-execution* step | That executor already runs unsandboxed in the backend container; copying it for test execution would mean both the auto-fix edit step AND the test-run step execute unsandboxed back-to-back, compounding rather than reducing this milestone's core new risk | Keep the auto-fix *edit* step on the existing `agentic_coder.py` (Claude Agent SDK → LiteLLM) pattern, exactly as `dev_pipeline.py` does today — but route the **test execution** step into the new sandbox container, with the host-side cloned workspace bind-mounted read-write so the container only *runs* tests, never edits code |
| Installing scanners (`ruff`/`bandit`/`semgrep`/Playwright browsers) directly into `backend/Dockerfile` | Bloats the main backend image with tools only needed transiently for QA runs, and couples scanner-version upgrades to a full backend image rebuild/redeploy | Dedicated `qa-sandbox` image (see Installation) — scanners and browsers live there, versioned and rebuilt independently of the FastAPI backend |

## Stack Patterns by Variant

**If the cloned repo is Python:**
- Static analysis: `ruff` (lint) + `bandit` (security) + `mypy` (types, only if the repo is already configured for it)
- Unit tests: detect existing `pytest`/`unittest` setup from `requirements.txt`/`pyproject.toml`; generate tests using the repo's own fixtures/conventions
- Because: mirrors the existing `codebase_scan_service` philosophy of reading the repo's actual structure before acting, rather than assuming a stack

**If the cloned repo is JS/TS (e.g. this platform's own Next.js frontend, or any onboarded Node project):**
- Static analysis: the repo's own `eslint` config if present, else `semgrep` as language-agnostic fallback
- Unit tests: detect `vitest`/`jest` from `package.json`
- E2E: `playwright` regardless of the repo's own E2E tooling choice — Playwright drives any web app via real browser automation at the HTTP/DOM boundary, independent of the target's language/framework. This is the one component of the QA stack that is intentionally NOT "detect and reuse repo conventions"

**If the trigger is the post-merge auto-chain:**
- Run the full QA suite (unit + static + E2E) since the merged code is the new baseline for `main`
- Because: post-merge is the highest-stakes trigger — it confirms the just-merged PR didn't break `main`
- Implementation: follow `merge_pipeline.py`'s existing post-merge-hook shape exactly — isolated try/except around the QA call (mirroring the `codebase_scan_service.run(...)` call already there), so a QA failure or exception NEVER flips the merge pipeline's own `state_row.status` to "failed" or blocks its Jira comment

**If the trigger is `@jarvis run qa` (on-demand):**
- Same full suite, but allow targeting either `main` or an open PR's branch (reuse `pr_creator.find_and_merge_pr`'s existing branch-discovery logic in a read-only "find, don't merge" mode)
- Because: on-demand QA is explicitly useful as a pre-merge gate, which the merge-triggered auto-chain cannot offer

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|------------------|-------|
| `playwright` (Python) `1.49.x` | `mcr.microsoft.com/playwright:v1.49.0-*` image tag | Must match minor version exactly; mismatched browser binary vs. package version is the most common Playwright-in-Docker failure mode |
| `claude-agent-sdk==0.2.107` (existing pin) | `litellm` image `ghcr.io/berriai/litellm:main-latest` (existing, unpinned) | No new compatibility risk from QA — the auto-fix step reuses the exact integration `agentic_coder.py` already validates; no new env vars or auth scheme needed |
| `docker` Python SDK `7.1.x` | Docker Engine API version on host (Compose v2 / Engine 24+) | Verify the host's Docker Engine API version supports the SDK's default API-version negotiation — not a concern on any reasonably current Docker install, but worth a one-line smoke test before relying on it in CI |
| `bandit` `1.8.x` | Python `>=3.9` | Backend already on `python:3.12-slim`; no conflict |
| `tenacity` `9.0.x` | Python `>=3.8` | No conflict with existing `python:3.12-slim` base |

## Sources

- Direct repo inspection — `backend/services/agentic_coder.py`, `claude_code_executor.py`, `dev_pipeline.py`, `merge_pipeline.py`, `repo_clone.py`, `docker-compose.yml`, `backend/Dockerfile`, `backend/requirements.txt` (HIGH confidence — primary source, current state of this codebase as of 2026-06-23)
- Playwright/Docker image-version pairing requirement — established Playwright operational behavior (MEDIUM-HIGH confidence; verify exact current minor against `https://playwright.dev/python/docs/docker` at implementation time since Playwright ships frequent minor releases)
- Docker SDK for Python resource-limiting API (`mem_limit`, `nano_cpus`, `pids_limit`) — stable Docker Engine API surface across recent SDK majors (MEDIUM confidence on `7.1.0` being exactly "latest" at implementation time — verify against PyPI before pinning)
- `ruff`/`bandit`/`mypy`/`semgrep` version numbers — MEDIUM confidence; these tools release frequently, treat stated `0.8.x`/`1.8.x`/`1.13.x`/`1.9x.x` as "verify exact patch at implementation time," not exact pins to copy verbatim
- `tenacity` `9.0.x` — MEDIUM confidence, stable/mature library with infrequent breaking changes

---
*Stack research for: AI-SDLC Jira v1.8 — Autonomous QA Stage*
*Researched: 2026-06-23*
