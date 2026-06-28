# Architecture Research — SonarQube Integration

**Project:** AI-SDLC Jira — v2.0 SonarQube QA Integration
**Researched:** 2026-06-26

## New Components

| Component | Type | Purpose |
|-----------|------|---------|
| `sonarqube` compose service | Docker service | Hosts SonarQube Community Edition server |
| `sonarqube_data` volume | Docker volume | Persists SonarQube DB + analysis history |
| `backend/services/sonar_scanner.py` | Python module | Runs sonar-scanner, polls for result, extracts metrics |
| `backend/services/sonar_bootstrap.py` | Python module | One-time token creation + server readiness check on startup |

## Modified Components

| Component | Change |
|-----------|--------|
| `docker-compose.yml` | Add `sonarqube` service + volume; expose port 9000 |
| `backend/services/qa_pipeline.py` | Add Step 4e: run sonar scan after static analysis |
| `backend/services/confluence_reporter.py` (or equivalent) | Add `build_sonarqube_section(metrics)` method |
| `backend/requirements.txt` | No new deps needed (httpx already present) |

## Data Flow

```
qa_pipeline.py Step 4e
  → sonar_scanner.run_scan(repo_path, project_key)
      → docker run sonar-scanner-cli (on ai-sdlc-net, mounts cloned repo)
      → scanner outputs task ID to stdout
  → sonar_scanner.poll_task(task_id, timeout=300)
      → GET /api/ce/task?id=<taskId>  [every 5s until SUCCESS/FAILED/timeout]
  → sonar_scanner.get_metrics(project_key)
      → GET /api/qualitygates/project_status?projectKey=<key>
      → GET /api/measures/component?component=<key>&metricKeys=bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density
      → returns SonarMetrics dataclass
  → passed to confluence_reporter.build_sonarqube_section(metrics)
      → appended to QA Confluence page
```

## Network Topology

```
ai-sdlc-net (Docker bridge network)
├── hermes (FastAPI backend)
├── sonarqube  ← new; reachable at http://sonarqube:9000 from other containers
├── sonar-scanner-cli container (ephemeral; --rm; runs scan then exits)
│   └── mounts cloned repo volume; reaches sonarqube via network alias
└── (existing: playwright, app_container, etc.)
```

- sonar-scanner container is ephemeral (like the Playwright runner) — not a persistent service
- sonarqube server is persistent (always-on service like hermes/freellmapi)
- cloned repo is mounted via `-v` bind mount (same path the qa_pipeline already uses)

## Suggested Build Order

1. **Phase 29 — SonarQube Service Setup:** Add compose service, volume, bootstrap token creation, health-check wait utility
2. **Phase 30 — Scanner Integration:** `sonar_scanner.py` module, wire into `qa_pipeline.py` Step 4e, graceful degradation
3. **Phase 31 — Confluence Report Section:** `build_sonarqube_section()`, integrate into existing QA report builder, E2E test full pipeline
