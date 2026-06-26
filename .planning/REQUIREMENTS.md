# Requirements: AI-SDLC Jira

**Defined:** 2026-06-19
**Core Value:** Team members trigger AI-powered SDLC automation directly from Jira comment history, with every output linked back to the originating ticket.

---

# Milestone v1.9 Requirements — Playwright E2E Live Testing

**Goal:** Enable the QA pipeline to spin up the cloned target app in a live Docker container, generate accurate Playwright assertions against its real running URL, execute them, and surface pass/fail results back to Jira and Confluence.

## Active Requirements

### App Serving

- [ ] **SERVE-01**: QA pipeline detects target app type and serve command from cloned repo `package.json` scripts (looks for `preview`, `start`, or `dev` in order of preference for production-like serving)
- [ ] **SERVE-02**: QA pipeline builds and serves the target app in an ephemeral Docker container attached to the compose network, exposing it on a dynamically allocated host port
- [ ] **SERVE-03**: After starting the container, QA pipeline polls `GET /` until it receives HTTP 200 (or times out after a configurable limit, default 60s) before proceeding
- [ ] **SERVE-04**: Target app container is always torn down in a `finally` block — cleanup runs on pass, fail, timeout, or exception

### Playwright Generator

- [ ] **PWGEN-01**: The Claude playwright generator receives the live container URL as `BASE_URL` (no hardcoded `http://frontend:3000` fallback; URL is derived from the running container)
- [ ] **PWGEN-02**: The playwright generator is only invoked after `SERVE-03` health-check confirms the app is reachable — not merely on URL presence
- [ ] **PWGEN-03**: If the target app cannot be served (unsupported framework, build error, health-check timeout), the E2E stage is skipped with an informative skip note written to the QA report; the rest of the QA pipeline (unit tests, static analysis) continues normally

### Test Execution

- [ ] **EXEC-01**: Playwright tests execute against the live target app URL (the container URL from PWGEN-01)
- [ ] **EXEC-02**: E2E pass/fail results (test count, failure details) are included in the Confluence QA report and Jira comment alongside existing unit test and static analysis results

## Future Requirements (deferred)

- Persistent staging environment — app stays running between QA runs (deferred)
- Support for non-Node.js apps (Python/Flask, Rails, etc.) (deferred)
- Parallel container runs per ticket (deferred)

## Out of Scope

- Using `PLAYWRIGHT_BASE_URL` env var as user-configurable override — replaced by dynamic container URL
- Scaffolding E2E test infrastructure for repos that have none — v1.8 decision, unchanged

## Traceability

| REQ-ID   | Phase    | Plan |
|----------|----------|------|
| SERVE-01 | Phase 27 | 27-01 |
| SERVE-02 | Phase 27 | 27-01 |
| SERVE-03 | Phase 27 | 27-01 |
| SERVE-04 | Phase 27 | 27-01 |
| PWGEN-01 | Phase 28 | TBD  |
| PWGEN-02 | Phase 28 | TBD  |
| PWGEN-03 | Phase 28 | TBD  |
| EXEC-01  | Phase 28 | TBD  |
| EXEC-02  | Phase 28 | TBD  |
