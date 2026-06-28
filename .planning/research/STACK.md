# Stack Research — SonarQube Integration

**Project:** AI-SDLC Jira — v2.0 SonarQube QA Integration
**Researched:** 2026-06-26
**Confidence:** HIGH

## SonarQube Docker Service

- **Image:** `sonarqube:10-community` (Community Edition, free, LTS-stable)
- **Port:** 9000 (internal to compose network; expose 9000:9000 for local dev UI access)
- **Required env vars:**
  - `SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true` — mandatory in Docker (bypasses Elasticsearch OS checks)
- **Volume:** `sonarqube_data:/opt/sonarqube/data` — persists project configs and analysis history
- **Startup time:** 90–120 seconds; health-check: `GET /api/system/status` returns `{"status":"UP"}`
- **Memory:** minimum 1 GB RAM recommended; set `SONAR_WEB_JAVAOPTS=-Xmx512m -Xms128m` and `SONAR_CE_JAVAOPTS=-Xmx512m` in compose

## sonar-scanner Approach

- **Image:** `sonarsource/sonar-scanner-cli:5.0` — official CLI, no local Java needed
- **Run pattern (from Python):**
  ```python
  subprocess.run([
      "docker", "run", "--rm",
      "--network", "ai-sdlc-net",
      "-v", f"{cloned_repo_path}:/usr/src",
      "sonarsource/sonar-scanner-cli:5.0",
      f"-Dsonar.host.url=http://sonarqube:9000",
      f"-Dsonar.token={sonar_token}",
      f"-Dsonar.projectKey={project_key}",
      "-Dsonar.sources=.",
  ], check=True)
  ```
- **Returns:** scanner exit code + task ID from stdout (parse `ANALYSIS SUCCESSFUL, you can browse`)
- **Task ID extraction:** scanner prints `More about the report processing at http://sonarqube:9000/api/ce/task?id=<UUID>`

## Python API Client

- **Approach:** plain `httpx` (already in project via FastAPI ecosystem) — no new dep needed
- **Key endpoints:**
  - `GET /api/ce/task?id=<taskId>` — poll until `status` is `SUCCESS` or `FAILED`
  - `GET /api/qualitygates/project_status?projectKey=<key>` — quality gate overall pass/fail
  - `GET /api/measures/component?component=<key>&metricKeys=bugs,vulnerabilities,code_smells,coverage,duplicated_lines_density` — metric values
- **Auth:** `Authorization: Bearer <token>` header

## Configuration

- **Token bootstrap:** on SonarQube first start, create admin token via:
  `POST /api/user_tokens/generate` with `name=hermes-qa` (or set via env var `SONAR_TOKEN` in compose for automated setup)
- **Project key convention:** `{owner}__{repo}` (e.g. `acme__my-app`) — unique per GitHub repo
- **sonar-project.properties** (optional, placed in cloned repo root or passed via `-D` flags):
  ```
  sonar.projectKey=<owner>__<repo>
  sonar.sources=.
  sonar.exclusions=**/node_modules/**,**/.git/**
  ```

## Integration Points

- **docker-compose.yml:** add `sonarqube` service + `sonarqube_data` named volume; attach to `ai-sdlc-net`
- **qa_pipeline.py:** new step after existing static analysis — run sonar-scanner, poll `ce/task`, fetch metrics
- **New module:** `backend/services/sonar_scanner.py` — encapsulates scan + poll + metrics extraction
- **Confluence reporter:** add `build_sonarqube_section(metrics)` to existing QA report builder

## What NOT to Add

- PostgreSQL for SonarQube — embedded H2 sufficient for single-node, single-project use
- Branch/PR decoration — Community Edition supports one branch per project key only
- `python-sonarqube-api` PyPI package — httpx covers all needed endpoints without extra dep
- SonarLint, developer IDE plugins — out of scope
