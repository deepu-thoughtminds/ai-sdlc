# Features Research — SonarQube Integration

**Project:** AI-SDLC Jira — v2.0 SonarQube QA Integration
**Researched:** 2026-06-26

## Table Stakes (must have)

- **Quality Gate pass/fail** — the single boolean verdict every team cares about; shown prominently
- **Bug count** — static analysis detected bugs (reliability issues)
- **Vulnerability count** — security-relevant issues
- **Code smell count** — maintainability issues
- **Coverage %** — line coverage (requires test coverage data; degrade gracefully if absent)
- **Duplications %** — duplicated lines density
- **Project link** — deep link to SonarQube dashboard for drill-down

## Differentiators (nice to have)

- **Per-category severity breakdown** — BLOCKER / CRITICAL / MAJOR counts within bugs/vulnerabilities
- **New issues vs total** — delta since last scan (shows regression vs improvement)
- **Security hotspot count** — issues requiring manual review (Community Edition supports this)
- **Lines of code scanned** — gives context for metric magnitudes

## Anti-Features (skip)

- **Branch comparison** — Community Edition limitation (one branch per project key)
- **Pull request decoration** — requires Developer Edition
- **Historical trend charts** — complex to embed in Confluence; link to SonarQube UI instead
- **Detailed issue list** — too verbose for Confluence; link out for drill-down
- **SAST rule customization** — out of scope for QA pipeline integration

## Confluence Report Section

The SonarQube section appears after existing test results in the QA page:

```
## 🔍 Code Quality (SonarQube)

**Quality Gate:** ✅ PASSED  (or ❌ FAILED)

| Metric         | Value  |
|----------------|--------|
| Bugs           | 2      |
| Vulnerabilities| 0      |
| Code Smells    | 14     |
| Coverage       | 73.4%  |
| Duplications   | 1.2%   |

[View full report →](http://sonarqube:9000/dashboard?id=<projectKey>)
```

- Quality gate status badge is the first thing shown (pass/fail is what teams act on)
- Table format matches existing QA report style
- Link to SonarQube UI for drill-down (don't embed full issue list)

## User-Facing Behavior

| Scenario | Jira comment | Confluence page |
|----------|-------------|-----------------|
| Scan running | (no intermediate comment) | "SonarQube analysis in progress..." |
| Scan passed quality gate | included in final QA summary | Full metrics section added |
| Scan failed quality gate | QA report notes gate failure | Metrics section shows FAILED + counts |
| SonarQube unavailable | "SonarQube scan skipped (service unavailable)" note | Section omitted gracefully |
| Scan timeout | "SonarQube scan timed out after Ns" note | Section omitted gracefully |
