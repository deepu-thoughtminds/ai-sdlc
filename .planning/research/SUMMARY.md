# Project Research Summary

**Project:** AI-SDLC Jira — v2.0 SonarQube QA Integration
**Researched:** 2026-06-26

## Key Findings

### Stack Additions
- `sonarqube:10-community` Docker service + `sonarqube_data` volume → zero cost, self-hosted
- `sonarsource/sonar-scanner-cli:5.0` ephemeral container → runs scan against cloned repo on `ai-sdlc-net`
- `httpx` (already present) for SonarQube Web API calls → no new Python deps

### Feature Table Stakes
Quality gate pass/fail + bugs + vulnerabilities + code smells + coverage % + duplications % + deep link to SonarQube UI.

### Differentiators (optional phase 31+)
Severity breakdown (BLOCKER/CRITICAL counts), new-issues delta vs last scan.

### Watch Out For
1. **Startup latency:** SonarQube needs 90–120s to boot — health-check required before first scan
2. **Token bootstrap:** admin token must be created on first run before any scan
3. **Project key uniqueness:** use `{owner}__{repo}` pattern to avoid cross-repo contamination
4. **Graceful degradation:** sonar step must never hard-fail the QA pipeline — wrap everything in try/except
5. **vm.max_map_count:** use `SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true` to avoid Linux host config requirement

## Implications for Roadmap

**3 phases** is the natural split:

| Phase | Scope |
|-------|-------|
| 29 — SonarQube Service | Compose service, volume, health-check, token bootstrap, server-ready utility |
| 30 — Scanner Integration | `sonar_scanner.py`, qa_pipeline.py Step 4e, graceful degradation, unit tests |
| 31 — Confluence Report | `build_sonarqube_section()`, integrated QA report, E2E UAT |

## Sources
- SonarQube Community Edition Docker Hub: `sonarqube:10-community`
- SonarQube Web API: `/api/system/status`, `/api/ce/task`, `/api/qualitygates/project_status`, `/api/measures/component`
- sonar-scanner-cli Docker Hub: `sonarsource/sonar-scanner-cli:5.0`
- Existing project: `backend/services/qa_pipeline.py`, `docker-compose.yml`, Confluence reporter
