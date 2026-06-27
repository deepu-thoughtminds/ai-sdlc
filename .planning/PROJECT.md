# AI-SDLC Jira

## Current State: v2.0 Shipped — Planning Next Milestone

**Shipped:** v2.0 SonarQube QA Integration (2026-06-27)
Every Jira-triggered QA run now produces a Confluence QA page with SonarQube quality metrics (gate status, bugs, vulns, smells, coverage, duplications, dashboard link). Pipeline degrades gracefully when SonarQube is unavailable.

**Codebase state:** Python (FastAPI) backend + Next.js frontend + Docker Compose. Phases 1–31 complete. QA pipeline fully wired: unit tests → static analysis → sonar-scanner → Playwright E2E → Confluence report.

## Previous Milestone: v2.0 SonarQube QA Integration

**Goal:** Embed SonarQube static analysis into the QA pipeline so every Jira-triggered QA run produces a code quality report published to the Confluence QA page.

**Target features:**
- SonarQube Community Edition as a Docker Compose service (self-hosted)
- QA pipeline step: run sonar-scanner against the cloned repo, wait for analysis to complete
- Extract key metrics: bugs, vulnerabilities, code smells, coverage, quality gate pass/fail
- SonarQube report section included in the Confluence QA page alongside existing test results

## Previous Milestone: v1.9 Playwright E2E Live Testing (shipped 2026-06-26)

The QA pipeline now spins up the target app in an ephemeral Docker container on the compose network, gates Playwright generation on a confirmed HTTP 200 health-check, and tears down the container on every exit path. E2E pass/fail results surface in the Confluence QA report and Jira comment.

## Previous Milestone: v1.8 Autonomous QA Stage (complete)

**Goal:** Add the QA stage after code generation — triggered both automatically post-merge and via explicit `@jarvis run qa` comment trigger, generating unit tests, static analysis, and Playwright-based E2E tests, executing them in the cloned repo sandbox, attempting a bounded auto-fix loop on failures, and reporting final results back to the Jira comment.

**Target features:**
- QA stage auto-chains after the dev pipeline's PR merge completes
- `@jarvis run qa` comment trigger to (re-)run QA on demand
- Test generation: unit tests + static analysis (lint/type-check/security scan) + Playwright E2E tests, using freellmapi against the cloned repo and existing codebase context (`.hermes/codebase.md`)
- Tests executed in the cloned repo sandbox using the project's existing test runner / Playwright
- Auto-fix loop: on failure, agent attempts to autonomously fix code and re-run QA, up to a bounded retry limit
- Final QA results (pass/fail summary, failure details after exhausting retries) posted back to the Jira comment

## Previous Milestone: v1.7 Agentic Codegen via LiteLLM + Claude Agent SDK (complete)

Phase 22 complete. Replaced the freellmapi text-completion codegen path with a fully agentic coding loop: Claude Agent SDK → LiteLLM proxy (Anthropic→OpenAI translation) → freellmapi → free LLMs.

## Milestone Before That: v1.6 Context-Aware Codebase Scanning (complete)

All 4 phases (18-21) complete. Codebase scan service, snapshot refresh, describe pipeline context, and architecture pipeline context all shipped. See `.planning/milestones/v1.6-REQUIREMENTS.md` for full requirement traceability.

## Earlier Milestone: v1.5 GitHub Dev Pipeline & LLM Intent Routing (complete)

**Goal:** Automate the developer stage end-to-end — from reading the published Confluence architecture to cloning the GitHub repo, making code changes, raising a PR, and merging it — all triggered from Jira comment mentions processed by an LLM-based intent router instead of hardcoded keyword matching.

**Target features:**
- GitHub repo field (`github_repo` owner/repo slug) added to project onboarding (web app form + DB)
- `@jarvis start coding` trigger: reads Confluence architecture page for the ticket, clones the GitHub repo, makes autonomous code changes via freellmapi, commits + pushes + raises PR, posts PR link to Jira comment
- `@jarvis merge pr to main branch` trigger: merges the open PR and posts merge status back to Jira comment
- LLM-based intent router replaces hardcoded `KNOWN_STAGES` whitelist in `mention_parser.py` — the LLM extracts intent and entities from free-text `@jarvis` phrases

## Even Earlier Milestone: v1.4 Smart Architecture & Confluence Publishing (complete)

**Goal:** Replace all direct Jira REST calls in the platform with mcp-atlassian MCP tool calls routed through the Hermes agent, so every Jira interaction (posting comments, updating descriptions, fetching sprint backlog, assigning issues) uses the MCP protocol.

**Target features:**
- mcp-atlassian Docker service (sooperset/mcp-atlassian) with per-request credential support for multi-project use
- Hermes async MCP client layer connecting to mcp-atlassian over HTTP with typed tool wrappers
- Hermes internal Jira API that the backend calls instead of JiraClient (comment, description, backlog, assign)
- Backend migration: JiraClient removed; all 5 Jira operations route through MCP tools

## What This Is

An agentic AI platform that augments the Jira Scrum pipeline by embedding a Hermes agent into the Jira comment history. Team members trigger the agent via `@agent-name` mentions in Jira comments, and it automates SDLC stages: elaborating feature descriptions, generating architecture diagrams, making code changes, and running QA — all surfaced back into the ticket's comment history.

## Core Value

Team members trigger AI-powered SDLC automation directly from Jira comment history, with every output (descriptions, architecture, PRs, test results) linked back to the originating ticket.

## Requirements

### Validated

- ✓ Confluence QA page includes SonarQube section: gate status, bugs, vulns, smells, coverage, duplications, dashboard link — v2.0 Phase 31
- ✓ sonar-scanner runs in QA pipeline after static analysis; CE task API polled until complete — v2.0 Phase 30
- ✓ SonarQube CE runs persistently in Docker Compose with readiness polling and idempotent token bootstrap — v2.0 Phase 29
- ✓ QA pipeline continues gracefully when SonarQube unavailable; Confluence shows fallback note — v2.0 Phase 30–31
- ✓ QA pipeline runs E2E tests against live ephemeral Docker container URL — v1.9 Phase 28
- ✓ Container torn down after test run; ephemeral per QA ticket — v1.9 Phase 27
- ✓ E2E header in Jira comment shows live URL when available — v1.9 Phase 28
- ✓ Container failure gracefully skips E2E, pipeline continues — v1.9 Phase 28
- ✓ Playwright generator receives confirmed-live BASE_URL; generation gated on HTTP 200 health-check — v1.9 Phase 27-28

### Active

- [ ] Hermes agent listens for Jira webhook events and processes `@agent-name` comment triggers
- [ ] Business user can trigger agent to elaborate a 2-3 sentence epic/story description using sprint backlog context and codebase knowledge (gsd-graphify)
- [ ] Agent posts elaborated description to comment history, awaits user approval, then updates Jira epic/story via Jira MCP
- [ ] Business user can trigger agent to assign epic/story to an architecture team member via Jira comment
- [ ] Architect can trigger agent (`@jarvis architecture`) to generate a single recommended architecture for the requested change, with depth (text-only vs. diagram+components) decided by the agent based on change complexity, published to Confluence via MCP, with link posted back to Jira comment
- [ ] Architect can approve architecture in comment history and trigger agent to assign epic/story to a developer
- [ ] Developer can trigger agent (`@jarvis start coding`) to read the Confluence architecture page, clone the project GitHub repo, autonomously make code changes, raise a PR, and post the PR link to the Jira comment
- [ ] Developer can trigger agent (`@jarvis merge pr to main branch`) to merge the open PR and update the Jira comment with merge status
- [ ] Developer can assign merged PR to QA via comment; agent generates test cases, triggers test runs, and reports results back to Jira comment
- [ ] Hermes agent and freellmapi run in Docker containers; freellmapi handles all heavy LLM tasks (code gen, architecture, test gen)
- [ ] Web app (Next.js + FastAPI) provides multi-project dashboard for onboarding projects with Jira, GitHub, and Confluence credentials
- [ ] Project credentials stored encrypted in the web app database and used by Hermes agent at runtime

### Out of Scope

- Mobile app — web-first for v1
- Real-time pipeline status streaming — comment-based async is sufficient for v1
- SSO/OAuth for the web app — basic auth sufficient for v1
- Self-hosted Jira support — cloud Jira only for v1

## Context

- **Trigger mechanism:** Jira webhooks fire on comment events; the agent server receives the webhook, parses `@agent-name` mentions, and routes to the appropriate pipeline stage handler
- **LLM routing:** freellmapi (free coding LLMs) handles all heavy tasks; Hermes uses its own model for lightweight orchestration and routing decisions
- **Code autonomy:** When developer triggers the dev stage, agent reads codebase (via gsd-graphify), writes code changes, and opens a PR — fully autonomous until PR review
- **Codebase context:** gsd-graphify skill used at description elaboration and dev stages to understand existing architecture and patterns
- **Architecture output:** drawio skill (Agents365-ai/drawio-skill) generates diagrams; Confluence MCP publishes the architecture page
- **Auth per project:** Each onboarded project stores its Jira URL, GitHub token, Confluence URL, and API keys encrypted in the web app DB
- **v1 scope:** Description elaboration stage + architecture stage working end-to-end; dev and QA stages are v2

## Constraints

- **Tech Stack:** Python (FastAPI) backend + Next.js frontend + Docker Compose for service orchestration
- **LLM Cost:** freellmapi used for all heavy tasks to minimize API costs; must integrate with freellmapi Docker service
- **Integration:** Jira MCP, Confluence MCP, GitHub API/MCP required; drawio skill from Agents365-ai/drawio-skill
- **Security:** Project credentials must be encrypted at rest in DB; never logged or exposed in API responses
- **Autonomy:** Dev stage is fully autonomous code changes — requires robust codebase reading and PR creation

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Jira webhook for trigger (not polling) | Real-time response, no polling overhead | ✓ Good — zero polling overhead confirmed |
| freellmapi for all heavy LLM tasks | Cost control; free coding models sufficient for code/arch/test gen | ✓ Good — used through v1.9 |
| Comment history as the UX surface | Keeps all AI interaction in Jira without a separate UI per stage | ✓ Good — consistent pattern across all stages |
| v1 = description + architecture stages only | Reduces risk; these stages have clearest requirements and least autonomy risk | ✓ Good — dev/QA expanded incrementally in v1.5–v1.9 |
| Credentials in web app DB (encrypted) | Simple for multi-project setup; avoid per-deployment env var complexity | ✓ Good — used for all pipeline stages |
| Next.js + FastAPI stack | Next.js for rich dashboard UI; FastAPI for async webhook handling and agent orchestration | ✓ Good — stable through v1.9 |
| app_container uses network-internal URL as BASE_URL | Playwright containers run as siblings on ai-sdlc-net; internal URL reachable by docker DNS | ✓ Good — host port used only for debug |
| E2E generation gated on SERVE-03 health-check (not URL presence) | Prevents test generation against an unresponsive server; avoids flaky tests | ✓ Good — validated in UAT 4/4 |
| TYPE_CHECKING guard for SonarMetrics import in confluence_client.py | Avoids circular import (sonar_scanner → test_executor, confluence_client → hermes_client) with zero runtime cost | ✓ Good — confirmed in Phase 31 |
| dashboard_url constructed from env var SONAR_URL + project_key (not API response) | Prevents external data injection into rendered HTML URLs (T-31-02) | ✓ Good — Phase 31 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-27 after v2.0 milestone — SonarQube QA Integration shipped*
