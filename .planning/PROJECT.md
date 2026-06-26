# AI-SDLC Jira

## Current Milestone: v1.9 Playwright E2E Live Testing

**Goal:** Enable the QA pipeline to spin up the cloned target app in a live Docker container, generate accurate Playwright assertions against its real running URL, execute them, and surface pass/fail results back to Jira and Confluence.

**Target features:**
- Detect target app type (Vite/React, Next.js, etc.) from cloned repo and serve it in an ephemeral Docker container on the compose network
- Pass the live container URL as BASE_URL to the Claude playwright generator so assertions reflect actual running app content
- Playwright test execution runs against the live target app URL (not the ai-sdlc frontend)
- Container torn down after test run (ephemeral, per QA ticket run)
- QA report in Confluence and Jira comment includes E2E pass/fail results

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

(None yet — ship to validate)

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
| Jira webhook for trigger (not polling) | Real-time response, no polling overhead | — Pending |
| freellmapi for all heavy LLM tasks | Cost control; free coding models sufficient for code/arch/test gen | — Pending |
| Comment history as the UX surface | Keeps all AI interaction in Jira without a separate UI per stage | — Pending |
| v1 = description + architecture stages only | Reduces risk; these stages have clearest requirements and least autonomy risk | — Pending |
| Credentials in web app DB (encrypted) | Simple for multi-project setup; avoid per-deployment env var complexity | — Pending |
| Next.js + FastAPI stack | Next.js for rich dashboard UI; FastAPI for async webhook handling and agent orchestration | — Pending |

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
*Last updated: 2026-06-23 — milestone v1.8 (Autonomous QA Stage) started; v1.7 (Agentic Codegen) recorded as shipped*
