---
plan: 30-02
status: complete
phase: 30-scanner-integration
requirements: [SCAN-04]
gap_closure: true
key-files:
  modified:
    - backend/services/qa_pipeline.py
    - backend/tests/test_sonar_scanner.py
commits:
  - e23f76b
---

## Summary

Closed SCAN-04: moved `ensure_sonarqube_ready()` out of `run()` and into `_run_sonar_step`'s try block.

**What changed:**

- `_run_sonar_step` early-exit guard now checks only `SONAR_URL` (not `SONAR_TOKEN`), because `ensure_sonarqube_ready()` bootstraps the token on success.
- `ensure_sonarqube_ready()` is now the first call inside the existing try/except — a `SonarQubeNotReadyError` is caught by the same handler that covers all other scan failures, returning a non-None `TestResult` with descriptive stderr.
- Removed the bare `ensure_sonarqube_ready()` call from `run()` (old lines 343–345). A SonarQube availability failure can no longer abort the entire pipeline via the outer exception handler.
- Added `test_run_sonar_step_not_ready` to `test_sonar_scanner.py` covering the SCAN-04 path.

**Verification:**

- `pytest tests/test_sonar_scanner.py` → 9 passed (was 8; new test added)
- `grep ensure_sonarqube_ready qa_pipeline.py` → import line (68) + one call inside `_run_sonar_step` (212); not in `run()`

## Self-Check: PASSED
