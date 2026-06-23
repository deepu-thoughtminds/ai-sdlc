---
phase: 23-qa-foundation-sandbox-execution
verified: 2026-06-23T00:00:00Z
status: passed
score: 8/8 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gaps: []
---

# Phase 23: QA Foundation & Sandbox Execution Verification Report

**Phase Goal:** Build sandboxed execution foundation — test_executor.py (toolchain detection + subprocess execution), qa-sandbox Docker image, qa_pipeline.py skeleton, PipelineState.qa_attempt field, static analysis execution without LLM — establishing the right architectural boundary (LLM generates files; orchestrator runs them) before LLM test generation exists.

**Verified:** 2026-06-23
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

The phase goal is achieved. All five deliverables exist, are substantive (not stubs), and are correctly wired. The architectural boundary is established: `test_executor.py` is a pure-function module with no LLM calls; `qa_pipeline.py` orchestrates execution with `qa_attempt=0` committed before any execution begins; workspace cleanup runs unconditionally in a `finally` block; all subprocess calls use list-form args (AST-verified, no `shell=True` in live code).

---

## Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `qa-sandbox/Dockerfile` builds from `python:3.12-slim`, installs ruff/mypy/bandit + nodejs + eslint/typescript | VERIFIED | File exists, base image `python:3.12-slim`, nodesource node20, pip installs ruff/mypy/bandit, npm installs eslint/typescript, WORKDIR /workspace |
| 2 | `docker-compose.yml` contains `qa-sandbox` service and Docker socket mount on backend | VERIFIED | Lines 102, 106-107, 128-132: socket `/var/run/docker.sock` mounted in backend; `qa-sandbox` service with `image: qa-sandbox` present |
| 3 | `PipelineState` ORM has `qa_attempt` (Integer, nullable=True); both Pydantic schemas expose it | VERIFIED | `pipeline_state.py` line 86: `qa_attempt: int | None = None` (Create), line 107: `qa_attempt: int | None` (Public); ORM mapped_column confirmed in source |
| 4 | `detect_toolchain()` reads filesystem (pyproject.toml/setup.cfg/package.json) and returns ToolchainCommand list without any LLM call | VERIFIED | `test_executor.py`: pure function, no LLM import, filesystem checks with `os.path.isfile`, returns `list[ToolchainCommand]` |
| 5 | `run_command()` uses `subprocess.run()` in list form, never `shell=True`, returns `TestResult` with stdout/stderr/returncode/timed_out | VERIFIED | AST parse confirms zero `shell=` keywords in live code; `TestResult` dataclass has all four fields; `TimeoutExpired` caught, sets `timed_out=True, returncode=-1` |
| 6 | `QAPipeline.run()` commits `qa_attempt=0` before execution, runs static analysis, cleans workspace in `finally`, posts Jira comment | VERIFIED | `qa_pipeline.py` lines 105-106 commit `qa_attempt=0`; line 131 runs static analysis inside try; lines 149-153 `finally: shutil.rmtree(ignore_errors=True)`; lines 157-170 post Jira comment in own try/except |
| 7 | All subprocess calls use list form — `shell=True` never appears in live code in either module | VERIFIED | `grep shell=True` matches only docstring/comment lines; Python AST walk of `test_executor.py` finds zero `shell=` keywords in live AST nodes |
| 8 | Test suites pass: 36 tests across test_pipeline_state.py, test_test_executor.py, test_qa_pipeline.py | VERIFIED | `python3 -m pytest tests/test_pipeline_state.py tests/test_test_executor.py tests/test_qa_pipeline.py -x -q` → **36 passed, 0 failures** |

**Score:** 8/8 truths verified

---

## Requirement Traceability

| Req ID | Description | Status | Evidence |
|--------|-------------|--------|----------|
| TESTEXEC-01 | All test/static-analysis commands execute via `subprocess.run()` inside cloned workspace with hard per-command timeout (120s); output captured into structured `TestResult` | VERIFIED | `run_command()` uses `subprocess.run(cmd.command, capture_output=True, text=True, timeout=timeout)` with list-form args; `TestResult` dataclass captures stdout/stderr/returncode/timed_out |
| TESTEXEC-02 | Each QA run uses a fresh clone (never reuses dev/merge workspace); workspace cleaned up regardless of outcome | VERIFIED | `qa_pipeline.py` calls `clone_repository(github_repo, github_token)` inside `run()`; `finally: shutil.rmtree(cloned.workspace_path, ignore_errors=True)` runs unconditionally |
| TESTGEN-02 | Agent auto-detects toolchain (Python: ruff/mypy/bandit from pyproject.toml/setup.cfg; JS/TS: eslint/tsc/npm audit from package.json) without LLM invocation | VERIFIED | `detect_toolchain()` is pure-function filesystem detection; no LLM import or call anywhere in `test_executor.py` |
| AUTOFIX-04 | Auto-fix attempt count tracked in `PipelineState.qa_attempt` so loop progress is observable | VERIFIED | `qa_attempt: Mapped[int | None]` column exists in ORM; set to `0` before first execution in `qa_pipeline.run()` |

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `qa-sandbox/Dockerfile` | QA toolchain image: python:3.12-slim + ruff/mypy/bandit + node20 + eslint/typescript | VERIFIED | Substantive — 41 lines, all tools present, WORKDIR /workspace, no CMD |
| `docker-compose.yml` | qa-sandbox service + Docker socket mount on backend + env vars | VERIFIED | Socket at line 102, DOCKER_SOCKET/QA_SANDBOX_IMAGE env vars lines 106-107, qa-sandbox service lines 128-132 |
| `backend/models/pipeline_state.py` | `qa_attempt` Integer nullable=True on ORM + both schemas | VERIFIED | ORM column present; PipelineStateCreate line 86; PipelineStatePublic line 107 |
| `backend/services/test_executor.py` | ToolchainCommand/TestResult dataclasses, detect_toolchain(), run_command(), run_static_analysis() | VERIFIED | All four symbols present; pure-function module, no ORM/async imports |
| `backend/services/qa_pipeline.py` | Async run() coroutine: qa_attempt tracking, fresh clone, try/finally cleanup, Jira comment | VERIFIED | ~208-line module; all required steps present and wired |
| `backend/tests/test_test_executor.py` | Tests for toolchain detection and subprocess execution (mocked) | VERIFIED | 17 tests, all subprocess.run calls mocked, pass in full suite run |
| `backend/tests/test_qa_pipeline.py` | Tests for pipeline orchestration: qa_attempt persistence, cleanup, Jira comment | VERIFIED | 11 tests (10 spec + 1 bug-fix), all pass |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `qa_pipeline.py` | `test_executor.run_static_analysis` | import + call at line 131 | WIRED | `from services.test_executor import TestResult, run_static_analysis` |
| `qa_pipeline.py` | `PipelineState.qa_attempt` | ORM attribute assignment line 105 + db.commit() line 106 | WIRED | `state_row.qa_attempt = 0` committed before execution |
| `qa_pipeline.py` | `shutil.rmtree` in `finally` | lines 149-153 | WIRED | `finally: if cloned is not None: shutil.rmtree(cloned.workspace_path, ignore_errors=True)` |
| `test_executor.py` | `subprocess.run()` (list form) | inside `run_command()` | WIRED | List-form args confirmed by AST parse; no `shell=True` in live AST |
| `docker-compose.yml` | `qa-sandbox` service | `build: context: ./qa-sandbox` | WIRED | Image tagged `qa-sandbox`; backend gets `QA_SANDBOX_IMAGE` env var |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| 36 unit tests pass across all three test files | `python3 -m pytest tests/test_pipeline_state.py tests/test_test_executor.py tests/test_qa_pipeline.py -x -q` | **36 passed, 0 failures, 2 warnings** | PASS |
| No `shell=True` in live AST of test_executor.py | AST walk via `ast.parse` checking for `shell=` keyword nodes | Zero hits in live code | PASS |
| `qa_attempt` column in ORM and both Pydantic schemas | `grep -n 'qa_attempt' backend/models/pipeline_state.py` | 3 matches (ORM, Create, Public) | PASS |
| docker-compose.yml wires socket mount + qa-sandbox service | `grep -n 'qa-sandbox\|DOCKER_SOCKET\|docker.sock'` | Lines 102, 106-107, 128-132 all present | PASS |

---

## Anti-Patterns Found

None. No `TBD`, `FIXME`, or `XXX` markers found in phase files. Stubs documented in SUMMARY as intentional scope boundaries (Phase 24 will add LLM test generation) — these are commented scope markers referencing the next phase, not unresolved debt.

---

## Requirements Coverage

All four requirement IDs (TESTEXEC-01, TESTEXEC-02, TESTGEN-02, AUTOFIX-04) are mapped to this phase in REQUIREMENTS.md and are satisfied by the implementation verified above.

---

## Summary

Phase 23 goal is fully achieved. The sandboxed execution foundation is in place:

- The qa-sandbox Docker image is defined with the correct toolchain (ruff/mypy/bandit/eslint/tsc).
- docker-compose.yml registers the image and mounts the Docker socket into the backend service.
- `PipelineState.qa_attempt` column exists in the ORM and both Pydantic schemas.
- `test_executor.py` provides pure-function toolchain detection and subprocess execution with no LLM dependency.
- `qa_pipeline.py` skeleton mirrors merge_pipeline.py's structure: qa_attempt committed before execution, fresh clone per run, unconditional finally-block cleanup, Jira comment posting.
- The shell-injection threat (T-23-01) is verifiably mitigated: AST parse finds zero `shell=` keyword nodes in live code.
- 36 tests pass with zero failures.

---

_Verified: 2026-06-23_
_Verifier: Claude (gsd-verifier)_
