# Milestones

## v2.0 SonarQube QA Integration (Shipped: 2026-06-27)

**Phases completed:** 3 phases (29–31), 5 plans, 9 tasks
**Files changed:** ~8 | **Commits:** 9 | **Timeline:** 2026-06-27 (single day)
**Known gaps at close:** SONAR-01..03 checkboxes stale in REQUIREMENTS.md (satisfied; Phases 29 and 31 used UAT.md instead of VERIFICATION.md)

**Key accomplishments:**

- Built `sonar_client.py` — `wait_until_ready()` polls SonarQube `/api/system/status`; `bootstrap_token()` idempotently provisions `jarvis-scanner` API token; `ensure_sonarqube_ready()` wired into QA pipeline (SONAR-01..03)
- Added sonarqube:lts-community Docker Compose service on host port 9001 with 3 named volumes and 90s start_period healthcheck (SONAR-01)
- Built `sonar_scanner.py` with `run_sonar_scan()` + `_poll_ce_task()` CE task polling; all failure paths return non-None `TestResult`; `_run_sonar_step` runs after static analysis, before Playwright E2E (SCAN-01..04)
- `SonarMetrics` dataclass + `fetch_sonar_metrics()` retrieve quality gate/bugs/vulns/smells/coverage/duplications from SonarQube API; `_render_sonar_section()` renders HTML table in Confluence QA page with dashboard deep link (REPORT-01..03)
- Graceful degradation: SonarQube down → scan skipped → Confluence shows "SonarQube scan unavailable" note; QA pipeline never aborted (SCAN-04, REPORT-03)

---

## v1.9 Playwright E2E Live Testing (Shipped: 2026-06-26)

**Phases completed:** 2 phases (27–28), 2 plans, 3 tasks
**Files changed:** 18 | **Lines:** +2489 / -375 | **Commits:** 15
**Timeline:** 2026-06-26 (single day)
**Known gaps at close:** SERVE-01..04 checkboxes not ticked in REQUIREMENTS.md (satisfied in Phase 27 VERIFICATION.md; tech debt only)

**Key accomplishments:**

- Built `app_container.py` — detects Node.js serve command (preview > start > dev), spins ephemeral Docker container on compose network, health-polls HTTP 200, guarantees teardown via `finally` (SERVE-01..04)
- Wired `managed_app_container` into `qa_pipeline.py` Step 4d — live container URL replaces hardcoded `PLAYWRIGHT_BASE_URL` env var (PWGEN-01)
- E2E generation gated on health-check confirmation; graceful skip note + pipeline continuation on `ValueError`/`ContainerStartError` (PWGEN-02, PWGEN-03)
- Both JS and Python Playwright docker run commands receive `-e BASE_URL=<live-url>` from context manager; E2E results in Confluence report and Jira comment (EXEC-01, EXEC-02)
- 25 unit tests covering all 9 requirements; 4/4 UAT scenarios passed

---

| Milestone | Name | Phases | Status | Shipped |
|-----------|------|--------|--------|---------|
| v1.0 | Core Platform | 1–4 | ✅ Shipped | 2026-06-18 |
| v1.1 | freellmapi | 5 | ✅ Shipped | 2026-06-18 |
| v1.2 | hermes-freellmapi | 6 | ✅ Shipped | 2026-06-18 |
| v1.3 | hermes-mcp-agent | 7–9 | ✅ Shipped | 2026-06-19 |
| v1.4 | smart-architecture | 10–13 | ✅ Shipped | 2026-06-19 |
| v1.5 | github-dev-pipeline | 14–17 | ✅ Shipped | 2026-06-21 |
| v1.6 | context-aware-codebase-scanning | 18–21 | ✅ Shipped | 2026-06-22 |
| v1.7 | agentic-codegen | 22 | ✅ Shipped | 2026-06-23 |
| v1.8 | autonomous-qa-stage | 23–26 | ✅ Shipped | 2026-06-24 |
| v1.9 | playwright-e2e-live-testing | 27–28 | ✅ Shipped | 2026-06-26 |
| v2.0 | sonarqube-qa-integration | 29–31 | ✅ Shipped | 2026-06-27 |

## v1.7 Summary — Agentic Codegen via LiteLLM + Claude Agent SDK

**Goal:** Replace the freellmapi one-shot text-completion codegen path with a fully agentic coding loop: Claude Agent SDK → LiteLLM proxy (Anthropic→OpenAI translation) → freellmapi → free LLMs.

**Phases:**

- Phase 22: Agentic Codegen — `litellm/` Docker service + `config.yaml`, `backend/services/agentic_coder.py`, updated `docker-compose.yml`/`dev_pipeline.py`/`requirements.txt`

**Requirements:** see `.planning/phases/22-agentic-codegen/22-REQUIREMENTS.md`

## v1.6 Summary — Context-Aware Codebase Scanning

**Goal:** Give every pipeline stage accurate codebase context by scanning the project repo at onboarding, committing a structured `.hermes/codebase.md` summary, and feeding it into description and architecture generation.

**Phases:**

- Phase 18: Codebase scan service — git clone + directory walk + targeted file reads → `.hermes/codebase.md`
- Phase 19: Snapshot refresh — post-merge hook re-runs scan; graceful degradation if file absent
- Phase 20: Describe pipeline integration — elaborations reference real module names and file paths
- Phase 21: Architecture pipeline integration — complexity classifier + architecture generation read codebase context

**Requirements:** 9/9 complete — see `.planning/milestones/v1.6-REQUIREMENTS.md`

**Key decisions:**

- Scan uses git clone + directory tree walk + targeted file reads (no LLM, no token cost)
- Output committed directly to main as `.hermes/codebase.md`
- Scan triggered automatically on project onboarding when `github_repo` saved
- Snapshot refresh hooks into `merge_pipeline.py` post-merge path
- Both `describe_pipeline.py` and `architecture_pipeline.py` read via GitHub API before LLM calls
