# Milestones

| Milestone | Name | Phases | Status | Shipped |
|-----------|------|--------|--------|---------|
| v1.0 | Core Platform | 1–4 | ✅ Shipped | 2026-06-18 |
| v1.1 | freellmapi | 5 | ✅ Shipped | 2026-06-18 |
| v1.2 | hermes-freellmapi | 6 | ✅ Shipped | 2026-06-18 |
| v1.3 | hermes-mcp-agent | 7–9 | ✅ Shipped | 2026-06-19 |
| v1.4 | smart-architecture | 10–13 | ✅ Shipped | 2026-06-19 |
| v1.5 | github-dev-pipeline | 14–17 | ✅ Shipped | 2026-06-21 |
| v1.6 | context-aware-codebase-scanning | 18–21 | ✅ Shipped | 2026-06-22 |

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
