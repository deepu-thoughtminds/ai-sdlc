# Pitfalls Research — SonarQube Integration

**Project:** AI-SDLC Jira — v2.0 SonarQube QA Integration
**Researched:** 2026-06-26

## Startup Time

**Risk:** SonarQube takes 90–120 seconds to boot. QA pipeline will fail if it hits the API before `status=UP`.

**Prevention:**
- Add `healthcheck` in docker-compose.yml:
  ```yaml
  healthcheck:
    test: ["CMD-SHELL", "curl -f http://localhost:9000/api/system/status | grep -q UP"]
    interval: 10s
    timeout: 5s
    retries: 15
    start_period: 90s
  ```
- In `sonar_bootstrap.py`, poll `GET /api/system/status` with retry before any scan attempt
- Do NOT add `depends_on: sonarqube` to hermes — hermes starts independently; scanner waits at runtime

## Authentication Token Bootstrap

**Risk:** SonarQube starts with default admin/admin credentials. Token must be created before first scan.

**Prevention:**
- On first boot: `POST /api/user_tokens/generate` with `name=hermes-qa`, `login=admin`, auth=`admin:admin`
- Store token in env var `SONAR_TOKEN` (via compose environment or project encrypted credentials)
- Run bootstrap idempotently: check if token exists before creating (catch 400 "token name already used")
- Phase 29 scope: bootstrap module runs at QA pipeline startup, not at server boot

## Project Key Conflicts

**Risk:** Community Edition uses project key as unique identifier. Scanning two repos with the same key corrupts results.

**Prevention:**
- Project key format: `{github_owner}__{repo_name}` — e.g. `acme__my-app`
- Derive from project's `github_repo` field (already stored in DB as `owner/repo`)
- Replace `/` with `__` — SonarQube project keys cannot contain `/`

## Quality Gate Polling Timeout

**Risk:** `GET /api/ce/task` may return `IN_PROGRESS` indefinitely if scanner hung or SonarQube is overloaded.

**Prevention:**
- Poll every 5 seconds with a hard timeout (300 seconds default, configurable)
- On timeout: log warning, return `SonarMetrics(status="TIMEOUT")`, continue QA pipeline (don't fail)
- Treat `FAILED` task status same as timeout — degrade gracefully, don't raise exception

## Memory / Resources

**Risk:** SonarQube Elasticsearch component needs `vm.max_map_count=262144` on Linux host — Docker will fail to start without it.

**Prevention:**
- Add to docker-compose.yml or host setup: `sysctl -w vm.max_map_count=262144`
- Or use `SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true` env var (acceptable for dev/single-node)
- Set JVM heap: `SONAR_WEB_JAVAOPTS=-Xmx512m` and `SONAR_CE_JAVAOPTS=-Xmx512m` to cap memory usage

## Graceful Degradation

**Risk:** If SonarQube is down (container crashed, OOM), QA pipeline hard-fails and no report is published.

**Prevention:**
- Wrap entire `sonar_scanner.run_scan()` in try/except
- On any exception (connection refused, timeout, scanner non-zero exit): return `SonarMetrics(status="UNAVAILABLE")`
- Confluence report section renders "SonarQube scan unavailable" note instead of metrics table
- QA pipeline continues to Playwright step regardless of sonar outcome
- Phase 30 scope: all error paths tested explicitly

## sonar-scanner Volume Mount Path

**Risk:** `docker run -v` bind mount of cloned repo only works if the path is accessible from the Docker daemon (not inside another container's filesystem).

**Prevention:**
- cloned repo must be on the host filesystem or a named volume — same constraint as existing Playwright runner
- Confirm qa_pipeline.py's clone path is a host-accessible directory (should already be, since Playwright uses same path)
- Pass absolute path to `-v` flag

## Community Edition Branch Limitation

**Risk:** Community Edition only analyzes the default branch. Attempting to pass `sonar.branch.name` will be silently ignored or error.

**Prevention:** Do not pass branch parameters. Always scan whatever is checked out (which is the PR-merged main branch in the existing pipeline flow).
